extends RefCounted
## Native posed surface measurements. Call sample() after frame_post_draw.

const PROXY_META := "_motion_clearance_proxy"
var _entries: Array[Dictionary] = []
var _surfaces: Array[Dictionary] = []
var _floor_y := 0.0
var _material_name := ""
var _referenced_count := 0
var _initialized := false
var _source_changed := false
var _unsupported := ""


func _mark_changed() -> void:
	_source_changed = true


func _collect(node: Node, result: Array[MeshInstance3D]) -> void:
	if node.has_meta(PROXY_META):
		return
	if node is MultiMeshInstance3D or node is SoftBody3D:
		_unsupported = "instanced or soft-body geometry is unsupported: %s" % node.name
		return
	if node is MeshInstance3D and node.mesh != null:
		result.append(node)
	for child in node.get_children():
		_collect(child, result)


func _skin_error(instance: MeshInstance3D, arrays: Array, format: int) -> String:
	var skeleton := instance.get_node_or_null(instance.skeleton) as Skeleton3D
	var reference := instance.get_skin_reference()
	if skeleton == null or reference == null or not reference.get_skeleton().is_valid():
		return "skinned surface requires a resolved Skeleton3D and registered skin"
	var skin := reference.get_skin()
	if skin == null or skin.get_bind_count() == 0:
		return "skin has no binds"
	for bind in range(skin.get_bind_count()):
		var name := skin.get_bind_name(bind)
		var bone := skeleton.find_bone(name) if not name.is_empty() else skin.get_bind_bone(bind)
		if bone < 0 or bone >= skeleton.get_bone_count() or not skin.get_bind_pose(bind).is_finite():
			return "skin has an invalid bone binding or non-finite inverse bind pose"
	var influences := 8 if format & Mesh.ARRAY_FLAG_USE_8_BONE_WEIGHTS else 4
	var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
	if arrays[Mesh.ARRAY_BONES] == null or arrays[Mesh.ARRAY_WEIGHTS] == null:
		return "skin bones and weights must both be present"
	var bones: PackedInt32Array = arrays[Mesh.ARRAY_BONES]
	var weights: PackedFloat32Array = arrays[Mesh.ARRAY_WEIGHTS]
	if bones.size() != vertices.size() * influences or weights.size() != bones.size():
		return "skin arrays do not match vertex count and influence format"
	for vertex in range(vertices.size()):
		var total := 0.0
		for influence in range(influences):
			var index := vertex * influences + influence
			if not is_finite(weights[index]) or weights[index] < 0.0:
				return "skin contains negative or non-finite weights"
			if bones[index] < 0 or bones[index] >= skin.get_bind_count():
				return "skin vertex references an invalid bind index"
			total += weights[index]
		if absf(total - 1.0) > 0.001:
			return "skin weights must sum to one (tolerance 0.001)"
	return ""


func initialize(model: Node3D, floor_y: float, material_name: String = "") -> String:
	if not _entries.is_empty() or _initialized:
		return "clearance helper can only be initialized once"
	if model == null or not model.is_inside_tree() or not is_finite(floor_y):
		return "clearance requires an in-tree model and finite floor Y"
	_floor_y = floor_y
	_material_name = material_name
	var instances: Array[MeshInstance3D] = []
	_collect(model, instances) # Collect before adding any private proxy children.
	if not _unsupported.is_empty():
		return _unsupported
	for instance in instances:
		var source := instance.mesh
		var path := String(model.get_path_to(instance))
		var morph_count := instance.get_blend_shape_count()
		var selected: Array[Dictionary] = []
		var skin_arrays: Array[Array] = []
		var skin_formats: Array[int] = []
		for surface in range(source.get_surface_count()):
			var primitive: int = source.surface_get_primitive_type(surface) if source is ArrayMesh else Mesh.PRIMITIVE_TRIANGLES
			if morph_count > 0 and primitive != Mesh.PRIMITIVE_TRIANGLES:
				return "%s: native morph baking only supports triangle surfaces" % path
			var material := instance.get_active_material(surface)
			var name := String(material.resource_name) if material != null else ""
			if not material_name.is_empty() and name != material_name:
				continue
			var arrays := source.surface_get_arrays(surface)
			if arrays.size() != Mesh.ARRAY_MAX or not arrays[Mesh.ARRAY_VERTEX] is PackedVector3Array:
				return "%s surface %d: missing 3D vertex array" % [path, surface]
			var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
			if vertices.is_empty():
				return "%s surface %d: empty geometry" % [path, surface]
			for vertex in vertices:
				if not vertex.is_finite():
					return "%s surface %d: non-finite geometry" % [path, surface]
			var indices := PackedInt32Array()
			if arrays[Mesh.ARRAY_INDEX] != null:
				indices = arrays[Mesh.ARRAY_INDEX]
			var referenced := PackedInt32Array()
			if indices.is_empty():
				for index in range(vertices.size()):
					referenced.append(index)
			else:
				var seen := {}
				for index in indices:
					if index < 0 or index >= vertices.size():
						return "%s surface %d: invalid vertex index" % [path, surface]
					if not seen.has(index):
						seen[index] = true
						referenced.append(index)
				referenced.sort()
			var skinned := arrays[Mesh.ARRAY_BONES] != null or arrays[Mesh.ARRAY_WEIGHTS] != null
			var format: int = source.surface_get_format(surface) if source is ArrayMesh else 0
			var skin_surface := -1
			if skinned:
				if not source is ArrayMesh or primitive != Mesh.PRIMITIVE_TRIANGLES:
					return "%s surface %d: native skin baking requires ArrayMesh triangles" % [path, surface]
				var error := _skin_error(instance, arrays, format)
				if not error.is_empty():
					return "%s surface %d: %s" % [path, surface, error]
				skin_surface = skin_arrays.size()
				skin_arrays.append(arrays)
				skin_formats.append(format)
			if morph_count > 0:
				if not source is ArrayMesh:
					return "%s: native morph baking requires ArrayMesh" % path
				var shapes := source.surface_get_blend_shape_arrays(surface)
				if shapes.size() != morph_count:
					return "%s surface %d: blend shape count mismatch" % [path, surface]
				for shape in shapes:
					if shape.size() != Mesh.ARRAY_MAX or not shape[Mesh.ARRAY_VERTEX] is PackedVector3Array or shape[Mesh.ARRAY_VERTEX].size() != vertices.size():
						return "%s surface %d: invalid blend shape geometry" % [path, surface]
					for vertex in shape[Mesh.ARRAY_VERTEX]:
						if not vertex.is_finite():
							return "%s surface %d: non-finite blend shape geometry" % [path, surface]
			var info := {"meshPath": path, "surface": surface,
				"surfaceName": source.surface_get_name(surface) if source is ArrayMesh else "",
				"material": name, "referencedVertexCount": referenced.size(), "skinned": skinned,
				"blendShapeCount": morph_count}
			_surfaces.append(info)
			_referenced_count += referenced.size()
			selected.append({"info": info, "indices": referenced, "vertices": vertices,
				"sourceIndices": indices, "skinSurface": skin_surface})
		if selected.is_empty():
			continue
		var proxy: MeshInstance3D
		if not skin_arrays.is_empty():
			proxy = MeshInstance3D.new()
			proxy.name = "MotionClearanceProxy"
			proxy.set_meta(PROXY_META, true)
			proxy.visible = false
			var mesh := ArrayMesh.new()
			for index in range(skin_arrays.size()):
				mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, skin_arrays[index], [], {}, skin_formats[index])
			proxy.mesh = mesh
			proxy.skin = instance.get_skin_reference().get_skin()
			instance.add_child(proxy)
			proxy.skeleton = proxy.get_path_to(instance.get_node(instance.skeleton))
			if not proxy.skin.changed.is_connected(_mark_changed):
				proxy.skin.changed.connect(_mark_changed)
		_entries.append({"instance": instance, "source": source, "selected": selected,
			"proxy": proxy, "skinFormats": skin_formats, "morphCount": morph_count})
		if not source.changed.is_connected(_mark_changed):
			source.changed.connect(_mark_changed)
	if _surfaces.is_empty():
		return "no mesh surfaces match the requested material" if not material_name.is_empty() else "model has no measurable mesh surfaces"
	_initialized = true
	return ""


func sample() -> Dictionary:
	if not _initialized or _source_changed:
		return {"error": "clearance is uninitialized or cached source geometry/skin changed"}
	var result := {"minimumY": INF, "belowFloorVertexCount": 0,
		"referencedVertexCount": _referenced_count, "lowest": {}, "surfaces": []}
	for entry in _entries:
		var instance: MeshInstance3D = entry.instance
		if not is_instance_valid(instance) or instance.mesh != entry.source or not instance.global_transform.is_finite():
			return {"error": "measured mesh was removed, replaced, or has a non-finite transform"}
		var mixed: ArrayMesh
		if int(entry.morphCount) > 0:
			for index in range(int(entry.morphCount)):
				if not is_finite(instance.get_blend_shape_value(index)):
					return {"error": "non-finite blend shape weight"}
			mixed = instance.bake_mesh_from_current_blend_shape_mix()
			if mixed == null or mixed.get_surface_count() != instance.mesh.get_surface_count():
				return {"error": "native blend shape baking failed or dropped surfaces"}
		var baked: ArrayMesh
		var proxy: MeshInstance3D = entry.proxy
		if proxy != null:
			if instance.get_skin_reference() == null or instance.get_skin_reference().get_skin() != proxy.skin:
				return {"error": "source skin binding changed"}
			if instance.get_node_or_null(instance.skeleton) != proxy.get_node_or_null(proxy.skeleton):
				return {"error": "source skeleton binding changed"}
			var reference := proxy.get_skin_reference()
			if reference == null or not reference.get_skeleton().is_valid() or RenderingServer.skeleton_get_bone_count(reference.get_skeleton()) < proxy.skin.get_bind_count():
				return {"error": "skin registration is not ready; sample after frame_post_draw on a real rendering backend"}
			if mixed != null:
				var mesh := ArrayMesh.new()
				for selected in entry.selected:
					if int(selected.skinSurface) >= 0:
						mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES,
							mixed.surface_get_arrays(int(selected.info.surface)), [], {},
							int(entry.skinFormats[int(selected.skinSurface)]))
				proxy.mesh = mesh
			baked = proxy.bake_mesh_from_current_skeleton_pose()
			if baked == null or baked.get_surface_count() != entry.skinFormats.size():
				return {"error": "native skin baking failed or dropped surfaces"}
		for selected in entry.selected:
			var vertices: PackedVector3Array = selected.vertices
			var arrays: Array = []
			if int(selected.skinSurface) >= 0:
				arrays = baked.surface_get_arrays(int(selected.skinSurface))
			elif mixed != null:
				arrays = mixed.surface_get_arrays(int(selected.info.surface))
			if not arrays.is_empty():
				vertices = arrays[Mesh.ARRAY_VERTEX]
				var indices := PackedInt32Array()
				if arrays[Mesh.ARRAY_INDEX] != null:
					indices = arrays[Mesh.ARRAY_INDEX]
				if vertices.size() != selected.vertices.size() or indices != selected.sourceIndices:
					return {"error": "native bake changed cached surface topology"}
			var surface: Dictionary = selected.info.duplicate()
			surface["minimumY"] = INF
			surface["belowFloorVertexCount"] = 0
			surface["lowestVertex"] = -1
			for index in selected.indices:
				var world: Vector3 = instance.global_transform * vertices[index]
				if not world.is_finite():
					return {"error": "non-finite posed geometry in %s surface %d" % [surface.meshPath, surface.surface]}
				if world.y < float(surface.minimumY):
					surface.minimumY = world.y
					surface.lowestVertex = index
				if world.y < _floor_y:
					surface.belowFloorVertexCount += 1
			result.belowFloorVertexCount += int(surface.belowFloorVertexCount)
			if float(surface.minimumY) < float(result.minimumY):
				result.minimumY = surface.minimumY
				result.lowest = {"meshPath": surface.meshPath, "surface": surface.surface,
					"surfaceName": surface.surfaceName, "material": surface.material, "vertex": surface.lowestVertex}
			result.surfaces.append(surface)
	return result


func describe() -> Dictionary:
	return {"floorY": _floor_y, "plane": {"normal": [0, 1, 0], "y": _floor_y},
		"materialFilter": _material_name, "referencedVertexCount": _referenced_count,
		"surfaces": _surfaces.duplicate(true),
		"scope": "Unique referenced vertices per selected source surface, in world space; counts are not welded across surfaces. Includes hidden source meshes.",
		"deformation": "Native blend shape bake followed by native skeleton bake on private hidden proxies; static surfaces retain node transforms.",
		"limitations": ["Requires a real rendering backend and sampling after frame_post_draw.",
			"Source topology, material selection and bind data are fixed at initialization.",
			"Triangle surfaces are required for skin or blend shape baking.",
			"Measures sampled geometry against an infinite horizontal plane; excludes shader vertex displacement, collision, thickness and swept motion between samples.",
			"Uses native bake precision and native blend shape weight thresholds."]}

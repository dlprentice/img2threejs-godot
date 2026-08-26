extends Node3D

const ASSET_SCENE := "res://imports/current/asset.glb"
const MANIFEST_PATH := "res://imports/current/asset_manifest.json"
const CONTEXT_PATH := "res://imports/current/validation_context.json"
const EVIDENCE_DIRECTORY := "res://evidence/current"
const SCREENSHOT_PATH := EVIDENCE_DIRECTORY + "/rts.png"
const WITHOUT_ASSET_PATH := EVIDENCE_DIRECTORY + "/rts_without_asset.png"
const ASSET_MASK_PATH := EVIDENCE_DIRECTORY + "/asset_mask.png"
const REPORT_PATH := EVIDENCE_DIRECTORY + "/godot_validation.json"
const TRANSFORM_TOLERANCE := 0.002

var failures: Array[String] = []
var mesh_count := 0
var lod1_hidden_count := 0


func _ready() -> void:
	call_deferred("_run_validation")


func _read_json(path: String) -> Dictionary:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		failures.append("cannot open %s" % path)
		return {}
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	if not parsed is Dictionary:
		failures.append("%s is not a JSON object" % path)
		return {}
	return parsed


func _vector3(values: Variant) -> Vector3:
	if not (
		values is Array
		or values is PackedFloat32Array
		or values is PackedFloat64Array
		or values is PackedInt32Array
		or values is PackedInt64Array
	) or values.size() != 3:
		return Vector3(INF, INF, INF)
	return Vector3(float(values[0]), float(values[1]), float(values[2]))


func _string_values(values: Variant) -> Array[String]:
	var result: Array[String] = []
	if values is Array or values is PackedStringArray:
		for value in values:
			result.append(String(value))
	return result


func _quaternion(values: Variant) -> Quaternion:
	if not values is Array or values.size() != 4:
		return Quaternion(INF, INF, INF, INF)
	return Quaternion(float(values[0]), float(values[1]), float(values[2]), float(values[3])).normalized()


func _close_vector(actual: Vector3, expected: Vector3, tolerance := TRANSFORM_TOLERANCE) -> bool:
	return actual.distance_to(expected) <= tolerance


func _transform_from_contract(contract: Dictionary) -> Transform3D:
	var rotation := _quaternion(contract.get("rotationQuaternion", []))
	var scale := _vector3(contract.get("scale", []))
	var basis := Basis(rotation).scaled(scale)
	return Transform3D(basis, _vector3(contract.get("translation", [])))


func _transform_matches(actual: Transform3D, contract: Dictionary) -> bool:
	var expected_translation := _vector3(contract.get("translation", []))
	var expected_scale := _vector3(contract.get("scale", []))
	var expected_rotation := _quaternion(contract.get("rotationQuaternion", []))
	var actual_rotation := actual.basis.get_rotation_quaternion().normalized()
	return (
		_close_vector(actual.origin, expected_translation)
		and _close_vector(actual.basis.get_scale(), expected_scale)
		and abs(actual_rotation.dot(expected_rotation)) >= 0.9999
	)


func _collect_nodes(node: Node, names: Dictionary) -> void:
	var node_name := String(node.name)
	if names.has(node_name):
		failures.append("duplicate imported node name: %s" % node_name)
	names[node_name] = node
	if node is MeshInstance3D:
		mesh_count += 1
	for child in node.get_children():
		_collect_nodes(child, names)


func _material(color: Color, metallic: float, roughness: float) -> StandardMaterial3D:
	var result := StandardMaterial3D.new()
	result.albedo_color = color
	result.metallic = metallic
	result.roughness = roughness
	return result


func _add_stage() -> Dictionary:
	var environment := WorldEnvironment.new()
	var environment_resource := Environment.new()
	environment_resource.background_mode = Environment.BG_COLOR
	environment_resource.background_color = Color(0.045, 0.055, 0.07)
	environment_resource.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	environment_resource.ambient_light_color = Color(0.42, 0.48, 0.58)
	environment_resource.ambient_light_energy = 0.68
	environment_resource.tonemap_mode = Environment.TONE_MAPPER_ACES
	environment.environment = environment_resource
	add_child(environment)

	var floor := MeshInstance3D.new()
	floor.name = "NeutralGround"
	var plane := PlaneMesh.new()
	plane.size = Vector2(14.0, 14.0)
	plane.material = _material(Color(0.12, 0.14, 0.17), 0.0, 0.86)
	floor.mesh = plane
	add_child(floor)

	var key := DirectionalLight3D.new()
	key.name = "KeyLight"
	key.light_color = Color(1.0, 0.88, 0.72)
	key.light_energy = 2.5
	key.shadow_enabled = true
	key.rotation_degrees = Vector3(-48.0, -34.0, 0.0)
	add_child(key)

	var fill := DirectionalLight3D.new()
	fill.name = "FillLight"
	fill.light_color = Color(0.45, 0.62, 1.0)
	fill.light_energy = 0.85
	fill.rotation_degrees = Vector3(-28.0, 142.0, 0.0)
	add_child(fill)

	var camera := Camera3D.new()
	camera.name = "RTSCamera"
	camera.projection = Camera3D.PROJECTION_ORTHOGONAL
	camera.size = 8.0
	add_child(camera)
	camera.position = Vector3(6.5, 6.2, 8.2)
	camera.look_at(Vector3(0.0, 0.9, 0.8), Vector3.UP)
	camera.current = true
	return {"environment": environment_resource, "floor": floor, "key": key, "fill": fill, "camera": camera}


func _material_contracts(manifest: Dictionary) -> Dictionary:
	var result := {}
	for value in manifest.get("materials", []):
		result[String(value.get("id", ""))] = value
	return result


func _validate_material(mesh_instance: MeshInstance3D, mesh_contract: Dictionary, materials: Dictionary) -> void:
	var expected_ids: Array = mesh_contract.get("materialIds", [])
	if mesh_instance.mesh == null or mesh_instance.mesh.get_surface_count() != expected_ids.size():
		failures.append("material surface count differs for %s" % mesh_instance.name)
		return
	for surface_index in range(mesh_instance.mesh.get_surface_count()):
		var expected_id := String(expected_ids[surface_index])
		var actual: Material = mesh_instance.get_active_material(surface_index)
		if actual == null or not actual is StandardMaterial3D:
			failures.append("material is missing or unsupported for %s" % mesh_instance.name)
			continue
		if not materials.has(expected_id):
			failures.append("manifest material is missing: %s" % expected_id)
			continue
		var expected: Dictionary = materials[expected_id]
		var base: Array = expected.get("baseColorFactor", [])
		if base.size() != 4:
			failures.append("manifest base color is invalid for %s" % expected_id)
			continue
		var expected_color := Color(float(base[0]), float(base[1]), float(base[2]), float(base[3]))
		var color_difference_raw: float = (
			abs(actual.albedo_color.r - expected_color.r)
			+ abs(actual.albedo_color.g - expected_color.g)
			+ abs(actual.albedo_color.b - expected_color.b)
			+ abs(actual.albedo_color.a - expected_color.a)
		)
		var expected_linear := expected_color.srgb_to_linear()
		var expected_srgb := expected_color.linear_to_srgb()
		var color_difference_linear: float = (
			abs(actual.albedo_color.r - expected_linear.r)
			+ abs(actual.albedo_color.g - expected_linear.g)
			+ abs(actual.albedo_color.b - expected_linear.b)
			+ abs(actual.albedo_color.a - expected_linear.a)
		)
		var color_difference_srgb: float = (
			abs(actual.albedo_color.r - expected_srgb.r)
			+ abs(actual.albedo_color.g - expected_srgb.g)
			+ abs(actual.albedo_color.b - expected_srgb.b)
			+ abs(actual.albedo_color.a - expected_srgb.a)
		)
		if min(color_difference_raw, min(color_difference_linear, color_difference_srgb)) > 0.04:
			failures.append(
				"base color differs for %s: actual=%s expected=%s linear=%s"
				% [mesh_instance.name, actual.albedo_color, expected_color, expected_linear]
			)
		if abs(actual.metallic - float(expected.get("metallicFactor", -1.0))) > 0.01:
			failures.append("metallic factor differs for %s" % mesh_instance.name)
		if abs(actual.roughness - float(expected.get("roughnessFactor", -1.0))) > 0.01:
			failures.append("roughness factor differs for %s" % mesh_instance.name)
		if actual.cull_mode != BaseMaterial3D.CULL_BACK:
			failures.append("backface culling differs for %s" % mesh_instance.name)


func _validate_bounds(mesh_instance: MeshInstance3D, contract: Dictionary) -> void:
	if mesh_instance.mesh == null:
		return
	var bounds: Dictionary = contract.get("bounds", {})
	var expected_min := _vector3(bounds.get("min", []))
	var expected_max := _vector3(bounds.get("max", []))
	var actual := mesh_instance.mesh.get_aabb()
	if not _close_vector(actual.position, expected_min, 0.01) or not _close_vector(actual.end, expected_max, 0.01):
		failures.append("local bounds differ for %s" % mesh_instance.name)


func _validate_mesh_contracts(manifest: Dictionary, names: Dictionary, model: Node3D) -> Dictionary:
	var contracts := {}
	var materials := _material_contracts(manifest)
	for value in manifest.get("meshNodes", []):
		var contract: Dictionary = value
		var node_id := String(contract.get("id", ""))
		contracts[node_id] = contract
		if not names.has(node_id) or not names[node_id] is MeshInstance3D:
			failures.append("manifest mesh is missing or wrong type: %s" % node_id)
			continue
		var node: MeshInstance3D = names[node_id]
		var parent_id: Variant = contract.get("parentId")
		if parent_id == null:
			if node.get_parent() != model and names.has(String(node.get_parent().name)) and contracts.has(String(node.get_parent().name)):
				failures.append("root mesh has a mesh parent: %s" % node_id)
		elif String(node.get_parent().name) != String(parent_id):
			failures.append("parent differs for %s: expected %s got %s" % [node_id, parent_id, node.get_parent().name])
		if not _transform_matches(node.transform, contract.get("transform", {})):
			failures.append("local transform differs for %s" % node_id)
		_validate_bounds(node, contract)
		_validate_material(node, contract, materials)
	return contracts


func _expected_world_transform(node_id: String, contracts: Dictionary, cache: Dictionary) -> Transform3D:
	if cache.has(node_id):
		return cache[node_id]
	var contract: Dictionary = contracts[node_id]
	var local := _transform_from_contract(contract.get("transform", {}))
	var parent_id: Variant = contract.get("parentId")
	var world := local if parent_id == null else _expected_world_transform(String(parent_id), contracts, cache) * local
	cache[node_id] = world
	return world


func _validate_world_transforms(contracts: Dictionary, names: Dictionary) -> void:
	var cache := {}
	for node_id in contracts:
		if not names.has(node_id) or not names[node_id] is Node3D:
			continue
		var expected := _expected_world_transform(node_id, contracts, cache)
		var actual: Transform3D = names[node_id].global_transform
		if actual.origin.distance_to(expected.origin) > 0.005:
			failures.append("world translation differs for %s" % node_id)
		if abs(actual.basis.get_rotation_quaternion().normalized().dot(expected.basis.get_rotation_quaternion().normalized())) < 0.9999:
			failures.append("world rotation differs for %s" % node_id)


func _validate_metadata_contracts(manifest: Dictionary, names: Dictionary) -> void:
	for collection_name in ["pivots", "sockets", "collisionShapes"]:
		for value in manifest.get(collection_name, []):
			var contract: Dictionary = value
			var node_id := String(contract.get("id", ""))
			if not names.has(node_id) or not names[node_id] is Node3D:
				failures.append("metadata node is missing or wrong type: %s" % node_id)
				continue
			var node: Node3D = names[node_id]
			var parent_id := String(contract.get("parentNodeId", contract.get("nodeId", "")))
			if String(node.get_parent().name) != parent_id:
				failures.append("metadata parent differs for %s" % node_id)
			if not _transform_matches(node.transform, contract.get("transform", {})):
				failures.append("metadata transform differs for %s" % node_id)
			if collection_name == "pivots":
				var found_hook := false
				for hook in manifest.get("animationHooks", []):
					if hook.get("nodeId") == contract.get("nodeId") and _close_vector(_vector3(hook.get("axis", [])), Vector3.UP):
						found_hook = true
				if not found_hook:
					failures.append("pivot axis contract differs for %s" % node_id)
			elif collection_name == "sockets" and node.has_meta("tags"):
				if _string_values(node.get_meta("tags")) != _string_values(contract.get("tags", [])):
					failures.append("imported socket tags differ for %s" % node_id)
			elif collection_name == "collisionShapes" and node.has_meta("dimensions"):
				if not _close_vector(_vector3(node.get_meta("dimensions")), _vector3(contract.get("dimensions", []))):
					failures.append("imported collision dimensions differ for %s" % node_id)


func _set_lod(manifest: Dictionary, names: Dictionary, level: int) -> int:
	var visible_count := 0
	for contract in manifest.get("meshNodes", []):
		var node_id := String(contract.get("id", ""))
		if names.has(node_id) and names[node_id] is MeshInstance3D:
			var visible: bool = int(contract.get("lodLevel", -1)) == level and not names[node_id].has_meta("sabotage_hidden")
			names[node_id].visible = visible
			if visible:
				visible_count += 1
	return visible_count


func _validate_lods(manifest: Dictionary, names: Dictionary) -> Dictionary:
	var levels: Array = manifest.get("lodLevels", [])
	if levels.size() != 2:
		failures.append("manifest must contain exactly two LOD levels")
		return {}
	var near: Dictionary = levels[0]
	var far: Dictionary = levels[1]
	if int(near.get("level", -1)) != 0 or int(far.get("level", -1)) != 1:
		failures.append("LOD levels are not ordered 0 then 1")
	if int(far.get("triangleCount", 0)) >= int(near.get("triangleCount", 0)):
		failures.append("LOD1 does not reduce triangles")
	var far_count := _set_lod(manifest, names, 1)
	var expected_far: Array = far.get("meshNodeIds", [])
	if far_count != expected_far.size():
		failures.append("explicit LOD1 switch did not expose every far mesh")
	var near_count := _set_lod(manifest, names, 0)
	var expected_near: Array = near.get("meshNodeIds", [])
	if near_count != expected_near.size():
		failures.append("explicit LOD0 switch did not restore every near mesh")
	lod1_hidden_count = expected_far.size()
	return {"lod0Visible": near_count, "lod1Visible": far_count, "switching": "explicit-wrapper-policy"}


func _add_manifest_collision(manifest: Dictionary, names: Dictionary) -> Dictionary:
	var collisions: Array = manifest.get("collisionShapes", [])
	if collisions.size() != 1:
		failures.append("manifest must contain exactly one collision shape")
		return {}
	var contract: Dictionary = collisions[0]
	var parent_name := String(contract.get("nodeId", ""))
	if not names.has(parent_name) or not names[parent_name] is Node3D:
		failures.append("collision parent is missing: %s" % parent_name)
		return {}
	var dimensions := _vector3(contract.get("dimensions", []))
	if not dimensions.is_finite() or dimensions.x <= 0 or dimensions.y <= 0 or dimensions.z <= 0:
		failures.append("collision dimensions are invalid")
		return {}
	var body := StaticBody3D.new()
	body.name = "ManifestCollisionBody"
	names[parent_name].add_child(body)
	var shape_node := CollisionShape3D.new()
	shape_node.name = String(contract.get("id", "manifest-collision"))
	var box := BoxShape3D.new()
	box.size = dimensions
	shape_node.shape = box
	shape_node.transform = _transform_from_contract(contract.get("transform", {}))
	body.add_child(shape_node)
	return {"id": String(contract.get("id", "")), "dimensions": contract.get("dimensions", []), "body": body}


func _validate_coordinate_contract(manifest: Dictionary, names: Dictionary) -> Dictionary:
	var coordinate: Dictionary = manifest.get("coordinateSystem", {})
	if coordinate.get("unit") != "meter" or abs(float(coordinate.get("metersPerUnit", 0.0)) - 1.0) > 0.000001:
		failures.append("metric scale contract differs")
	if coordinate.get("handedness") != "right" or coordinate.get("upAxis") != "+Y" or coordinate.get("forwardAxis") != "+Z":
		failures.append("coordinate orientation contract differs")
	var minimum_y := INF
	for value in manifest.get("meshNodes", []):
		if int(value.get("lodLevel", -1)) != 0:
			continue
		var node_id := String(value.get("id", ""))
		if not names.has(node_id) or not names[node_id] is MeshInstance3D:
			continue
		var mesh_node: MeshInstance3D = names[node_id]
		var box := mesh_node.mesh.get_aabb()
		for x in [box.position.x, box.end.x]:
			for y in [box.position.y, box.end.y]:
				for z in [box.position.z, box.end.z]:
					minimum_y = min(minimum_y, (mesh_node.global_transform * Vector3(x, y, z)).y)
	if minimum_y < -0.01 or minimum_y > 0.25:
		failures.append("asset ground placement is outside tolerance: %.4f" % minimum_y)
	if names.has("primary-weapon") and names.has("muzzle-vfx"):
		var direction: Vector3 = names["muzzle-vfx"].global_position - names["primary-weapon"].global_position
		if direction.length() < 0.1 or direction.normalized().dot(Vector3(0.0, 0.0, 1.0)) < 0.98:
			failures.append("weapon/socket alignment is not canonical +Z forward")
	return {"minimumWorldY": minimum_y, "metersPerUnit": 1.0, "upAxis": "+Y", "forwardAxis": "+Z"}


func _validate_turret_motion(names: Dictionary) -> Dictionary:
	if not names.has("turret") or not names.has("muzzle-vfx"):
		return {}
	var turret: Node3D = names["turret"]
	var muzzle: Node3D = names["muzzle-vfx"]
	var original_transform := turret.transform
	var before := muzzle.global_position
	turret.rotate_y(deg_to_rad(30.0))
	var after := muzzle.global_position
	turret.transform = original_transform
	if before.distance_to(after) < 0.25:
		failures.append("turret yaw did not move the muzzle socket")
	return {"yawDegrees": 30.0, "muzzleTravelMeters": before.distance_to(after)}


func _image_difference(with_asset: Image, without_asset: Image) -> Dictionary:
	var changed := 0
	var sampled := 0
	var minimum_x := with_asset.get_width()
	var minimum_y := with_asset.get_height()
	var maximum_x := -1
	var maximum_y := -1
	for y in range(0, with_asset.get_height(), 2):
		for x in range(0, with_asset.get_width(), 2):
			var a := with_asset.get_pixel(x, y)
			var b := without_asset.get_pixel(x, y)
			if abs(a.r - b.r) + abs(a.g - b.g) + abs(a.b - b.b) > 0.06:
				changed += 1
				minimum_x = min(minimum_x, x)
				minimum_y = min(minimum_y, y)
				maximum_x = max(maximum_x, x)
				maximum_y = max(maximum_y, y)
			sampled += 1
	return {
		"changedPixelRatio": float(changed) / float(max(sampled, 1)),
		"changedSamples": changed,
		"boundingRectangle": [minimum_x, minimum_y, maximum_x, maximum_y],
		"boundingWidth": max(0, maximum_x - minimum_x + 1),
		"boundingHeight": max(0, maximum_y - minimum_y + 1),
	}


func _mask_metrics(image: Image) -> Dictionary:
	var visible := 0
	var sampled := 0
	var minimum_x := image.get_width()
	var minimum_y := image.get_height()
	var maximum_x := -1
	var maximum_y := -1
	for y in range(0, image.get_height(), 2):
		for x in range(0, image.get_width(), 2):
			var pixel := image.get_pixel(x, y)
			if pixel.r + pixel.g + pixel.b > 2.4:
				visible += 1
				minimum_x = min(minimum_x, x)
				minimum_y = min(minimum_y, y)
				maximum_x = max(maximum_x, x)
				maximum_y = max(maximum_y, y)
			sampled += 1
	return {
		"visiblePixelRatio": float(visible) / float(max(sampled, 1)),
		"visibleSamples": visible,
		"boundingRectangle": [minimum_x, minimum_y, maximum_x, maximum_y],
		"boundingWidth": max(0, maximum_x - minimum_x + 1),
		"boundingHeight": max(0, maximum_y - minimum_y + 1),
	}


func _capture_image() -> Image:
	await get_tree().process_frame
	await RenderingServer.frame_post_draw
	return get_viewport().get_texture().get_image()


func _solid_material(color: Color) -> StandardMaterial3D:
	var result := StandardMaterial3D.new()
	result.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	result.albedo_color = color
	result.cull_mode = BaseMaterial3D.CULL_DISABLED
	return result


func _asset_specific_evidence(model: Node3D, manifest: Dictionary, names: Dictionary, stage: Dictionary) -> Dictionary:
	var normal: Image = await _capture_image()
	if normal.is_empty() or normal.save_png(SCREENSHOT_PATH) != OK:
		failures.append("normal RTS screenshot could not be saved")
		return {}
	model.visible = false
	var without_asset: Image = await _capture_image()
	if without_asset.is_empty() or without_asset.save_png(WITHOUT_ASSET_PATH) != OK:
		failures.append("without-asset screenshot could not be saved")
	model.visible = true
	var difference := _image_difference(normal, without_asset)
	if float(difference["changedPixelRatio"]) < 0.015 or int(difference["boundingWidth"]) < 80 or int(difference["boundingHeight"]) < 50:
		failures.append("asset-specific normal-scene difference is too small: %s" % JSON.stringify(difference))

	stage["floor"].visible = false
	stage["key"].visible = false
	stage["fill"].visible = false
	stage["environment"].background_color = Color.BLACK
	stage["environment"].ambient_light_energy = 0.0
	var original_overrides := {}
	var white := _solid_material(Color.WHITE)
	var black := _solid_material(Color.BLACK)
	for contract in manifest.get("meshNodes", []):
		var node_id := String(contract.get("id", ""))
		if names.has(node_id) and names[node_id] is MeshInstance3D:
			original_overrides[node_id] = names[node_id].material_override
			names[node_id].material_override = white
	_set_lod(manifest, names, 0)
	var mask: Image = await _capture_image()
	if mask.is_empty() or mask.save_png(ASSET_MASK_PATH) != OK:
		failures.append("asset silhouette mask could not be saved")
	var mask_result := _mask_metrics(mask)
	if float(mask_result["visiblePixelRatio"]) < 0.015 or int(mask_result["boundingWidth"]) < 80 or int(mask_result["boundingHeight"]) < 50:
		failures.append("asset silhouette is not visible enough: %s" % JSON.stringify(mask_result))

	var component_pixels := {}
	for target in manifest.get("lodLevels", [])[0].get("meshNodeIds", []):
		for node_id in original_overrides:
			names[node_id].material_override = white if node_id == target else black
		var component_image: Image = await _capture_image()
		var component_result := _mask_metrics(component_image)
		component_pixels[String(target)] = component_result
		if float(component_result["visiblePixelRatio"]) < 0.0002:
			failures.append("mandatory mesh contributes no visible pixels: %s" % target)

	for node_id in original_overrides:
		names[node_id].material_override = original_overrides[node_id]
	stage["floor"].visible = true
	stage["key"].visible = true
	stage["fill"].visible = true
	stage["environment"].background_color = Color(0.045, 0.055, 0.07)
	stage["environment"].ambient_light_energy = 0.68
	return {"normalDifference": difference, "silhouette": mask_result, "componentVisibility": component_pixels}


func _percentile(samples: Array[float], fraction: float) -> float:
	var ordered := samples.duplicate()
	ordered.sort()
	var index := int(round((ordered.size() - 1) * fraction))
	return ordered[clamp(index, 0, ordered.size() - 1)]


func _render_timing_metrics(cpu_samples: Array[float]) -> Dictionary:
	var result := {
		"cpuFrameMilliseconds": _percentile(cpu_samples, 0.5),
		"cpuFrameP95Milliseconds": _percentile(cpu_samples, 0.95),
		"cpuFrameSampleCount": cpu_samples.size(),
		"gpuFrameMilliseconds": null,
		"renderCpuTimestampSpanMilliseconds": null,
		"gpuTimestampCount": 0,
	}
	var rendering_device: RenderingDevice = RenderingServer.get_rendering_device()
	if rendering_device == null:
		return result
	var count := rendering_device.get_captured_timestamps_count()
	result["gpuTimestampCount"] = count
	if count < 2:
		return result
	var first_gpu := rendering_device.get_captured_timestamp_gpu_time(0)
	var last_gpu := rendering_device.get_captured_timestamp_gpu_time(count - 1)
	var first_cpu := rendering_device.get_captured_timestamp_cpu_time(0)
	var last_cpu := rendering_device.get_captured_timestamp_cpu_time(count - 1)
	if last_gpu > first_gpu:
		result["gpuFrameMilliseconds"] = float(last_gpu - first_gpu) / 1000.0
	if last_cpu > first_cpu:
		result["renderCpuTimestampSpanMilliseconds"] = float(last_cpu - first_cpu) / 1000.0
	return result


func _write_report(report: Dictionary) -> void:
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(EVIDENCE_DIRECTORY))
	var file := FileAccess.open(REPORT_PATH, FileAccess.WRITE)
	if file == null:
		push_error("cannot write validation report")
		return
	file.store_string(JSON.stringify(report, "  ") + "\n")


func _bound_report(context: Dictionary, status: String) -> Dictionary:
	return {
		"status": status,
		"attemptId": context.get("attemptId", ""),
		"glbSha256": context.get("glbSha256", ""),
		"manifestSha256": context.get("manifestSha256", ""),
		"nonce": context.get("nonce", ""),
		"engineVersion": Engine.get_version_info().get("string", "unknown"),
	}


func _finish_failure(context: Dictionary, message: String) -> void:
	failures.append(message)
	var report := _bound_report(context, "fail")
	report["failures"] = failures
	_write_report(report)
	for failure in failures:
		push_error(failure)
	get_tree().quit(2)


func _run_validation() -> void:
	var context := _read_json(CONTEXT_PATH)
	if context.is_empty():
		_finish_failure({}, "validation context could not be loaded")
		return
	for path in [SCREENSHOT_PATH, WITHOUT_ASSET_PATH, ASSET_MASK_PATH, REPORT_PATH]:
		if FileAccess.file_exists(path):
			_finish_failure(context, "preexisting evidence is forbidden: %s" % path)
			return
	if FileAccess.get_sha256(ASSET_SCENE) != context.get("glbSha256"):
		_finish_failure(context, "GLB hash differs from validation context")
		return
	if FileAccess.get_sha256(MANIFEST_PATH) != context.get("manifestSha256"):
		_finish_failure(context, "manifest hash differs from validation context")
		return
	var manifest := _read_json(MANIFEST_PATH)
	if manifest.is_empty():
		_finish_failure(context, "manifest could not be loaded")
		return
	if manifest.get("generator", {}).get("attemptId") != context.get("attemptId"):
		_finish_failure(context, "manifest attempt differs from validation context")
		return
	var packed: Resource = load(ASSET_SCENE)
	if not packed is PackedScene:
		_finish_failure(context, "GLB did not import as PackedScene")
		return
	var model: Node3D = packed.instantiate()
	model.name = "ImportedVehicle"
	add_child(model)
	var names: Dictionary = {}
	_collect_nodes(model, names)
	var sabotage: Variant = context.get("sabotage")
	if sabotage == "missing-material" and names.has("hull"):
		names["hull"].material_override = StandardMaterial3D.new()
	elif sabotage == "backface-culling" and names.has("hull"):
		var bad_culling := names["hull"].get_active_material(0).duplicate() as StandardMaterial3D
		bad_culling.cull_mode = BaseMaterial3D.CULL_FRONT
		names["hull"].material_override = bad_culling
	elif sabotage == "below-floor":
		model.position.y = -100.0
	var expected_mesh_count := int(manifest.get("meshNodes", []).size())
	if mesh_count != expected_mesh_count:
		failures.append("imported mesh count %d does not match manifest %d" % [mesh_count, expected_mesh_count])
	var contracts := _validate_mesh_contracts(manifest, names, model)
	_validate_world_transforms(contracts, names)
	_validate_metadata_contracts(manifest, names)
	var lod_result := _validate_lods(manifest, names)
	var collision_result := _add_manifest_collision(manifest, names)
	var coordinate_result := _validate_coordinate_contract(manifest, names)
	var motion_result := _validate_turret_motion(names)
	var stage := _add_stage()

	if sabotage == "hidden":
		model.visible = false
	elif sabotage == "off-camera":
		model.position = Vector3(1000.0, 0.0, 1000.0)
	elif sabotage == "one-component":
		for node_id in ["turret", "weapon"]:
			if names.has(node_id):
				names[node_id].visible = false
				names[node_id].set_meta("sabotage_hidden", true)
	if not failures.is_empty():
		_finish_failure(context, "technical validation failed before rendering")
		return

	for _warmup_frame in range(30):
		await get_tree().process_frame
	await get_tree().physics_frame
	if collision_result.has("body"):
		var hull: Node3D = names["hull"]
		var query := PhysicsRayQueryParameters3D.create(
			hull.global_position + Vector3(0.0, 5.0, 0.0), hull.global_position - Vector3(0.0, 5.0, 0.0)
		)
		var hit := get_world_3d().direct_space_state.intersect_ray(query)
		if hit.is_empty() or hit.get("collider") != collision_result["body"]:
			failures.append("collision raycast did not hit the manifest collision body")
		collision_result.erase("body")
	var cpu_frame_samples: Array[float] = []
	for _sample_frame in range(30):
		await get_tree().process_frame
		await RenderingServer.frame_post_draw
		cpu_frame_samples.append(Performance.get_monitor(Performance.TIME_PROCESS) * 1000.0)
	var started := Time.get_ticks_usec()
	var evidence := await _asset_specific_evidence(model, manifest, names, stage)
	if not failures.is_empty():
		_finish_failure(context, "asset-specific render validation failed")
		return
	var elapsed_ms := float(Time.get_ticks_usec() - started) / 1000.0
	var timing_metrics := _render_timing_metrics(cpu_frame_samples)
	var report := _bound_report(context, "pass")
	report.merge(
		{
			"renderingDriver": RenderingServer.get_current_rendering_driver_name(),
			"videoAdapter": RenderingServer.get_video_adapter_name(),
			"meshCount": mesh_count,
			"hiddenLod1Count": lod1_hidden_count,
			"collision": collision_result,
			"lod": lod_result,
			"coordinateValidation": coordinate_result,
			"turretMotion": motion_result,
			"assetSpecificEvidence": evidence,
			"drawCalls": RenderingServer.get_rendering_info(RenderingServer.RENDERING_INFO_TOTAL_DRAW_CALLS_IN_FRAME),
			"captureFrameMilliseconds": elapsed_ms,
			"cpuFrameMilliseconds": timing_metrics["cpuFrameMilliseconds"],
			"cpuFrameP95Milliseconds": timing_metrics["cpuFrameP95Milliseconds"],
			"cpuFrameSampleCount": timing_metrics["cpuFrameSampleCount"],
			"gpuFrameMilliseconds": timing_metrics["gpuFrameMilliseconds"],
			"renderCpuTimestampSpanMilliseconds": timing_metrics["renderCpuTimestampSpanMilliseconds"],
			"gpuTimestampCount": timing_metrics["gpuTimestampCount"],
			"gpuTimingStatus": "MEASURED" if timing_metrics["gpuFrameMilliseconds"] != null else "UNAVAILABLE_IN_OFFICIAL_RUNTIME",
			"evidenceSha256": {
				"rts.png": FileAccess.get_sha256(SCREENSHOT_PATH),
				"rts_without_asset.png": FileAccess.get_sha256(WITHOUT_ASSET_PATH),
				"asset_mask.png": FileAccess.get_sha256(ASSET_MASK_PATH),
			},
			"failures": [],
		}
	)
	_write_report(report)
	print(JSON.stringify(report))
	get_tree().quit(0)

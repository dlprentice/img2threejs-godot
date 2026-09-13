extends SceneTree
# Synthetic native geometry checks; run through test_clearance_native.py.
const Helper = preload("res://clearance.gd")
var failures: Array[String] = []

func _initialize() -> void:
	run.call_deferred()

func check(condition: bool, message: String) -> void:
	if not condition:
		failures.append(message)

func arrays(y: float, skinned: bool) -> Array:
	var a := []
	a.resize(Mesh.ARRAY_MAX)
	a[Mesh.ARRAY_VERTEX] = PackedVector3Array([Vector3(0,y,0),Vector3(1,y,0),Vector3(0,y,1),Vector3(0,-99,0)])
	a[Mesh.ARRAY_INDEX] = PackedInt32Array([0,1,2,0,2,1])
	if skinned:
		a[Mesh.ARRAY_BONES] = PackedInt32Array([0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0])
		a[Mesh.ARRAY_WEIGHTS] = PackedFloat32Array([1,0,0,0,1,0,0,0,1,0,0,0,1,0,0,0])
	return a

func test_morph_skin() -> Array:
	var results: Array = []
	for mode in [Mesh.BLEND_SHAPE_MODE_RELATIVE, Mesh.BLEND_SHAPE_MODE_NORMALIZED]:
		var model := Node3D.new()
		model.position.y = 2
		root.add_child(model)
		var skeleton := Skeleton3D.new()
		skeleton.name = "Skeleton"
		skeleton.add_bone("root")
		model.add_child(skeleton)
		var skin := Skin.new()
		skin.add_named_bind("root", Transform3D.IDENTITY)
		var instance := MeshInstance3D.new()
		instance.name = "MixedMesh"
		instance.position.y = 3
		var mesh := ArrayMesh.new()
		mesh.blend_shape_mode = mode
		mesh.add_blend_shape("lower")
		for surface in range(2):
			# Static source surface 0 must not shift the proxy's skinned index 0.
			var a := arrays(1.0 if surface == 1 else 3.0, surface == 1)
			var shape := []
			shape.resize(Mesh.ARRAY_MAX)
			var v := PackedVector3Array()
			for point in a[Mesh.ARRAY_VERTEX]:
				v.append(Vector3(0,-2,0) if mode == Mesh.BLEND_SHAPE_MODE_RELATIVE else point + Vector3(0,-2,0))
			shape[Mesh.ARRAY_VERTEX] = v
			mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES,a,[shape])
			var material := StandardMaterial3D.new()
			material.resource_name = "skin" if surface == 1 else "static"
			mesh.surface_set_material(surface,material)
			mesh.surface_set_name(surface,material.resource_name)
		instance.mesh = mesh
		instance.skin = skin
		model.add_child(instance)
		instance.skeleton = instance.get_path_to(skeleton)
		instance.set_blend_shape_value(0,0.5)
		skeleton.set_bone_pose_position(0,Vector3(0,-0.25,0))
		var helper = Helper.new()
		var error: String = helper.initialize(model,5.0)
		check(error.is_empty(), "initialize mode %s: %s" % [mode,error])
		if error.is_empty():
			await process_frame
			await RenderingServer.frame_post_draw
			var sample: Dictionary = helper.sample()
			results.append({"mode":mode,"first":sample,"description":helper.describe()})
			check(not sample.has("error"), "first sample: %s" % sample)
			if not sample.has("error"):
				check(absf(float(sample.minimumY)-4.75)<0.0002,"morph plus skin world min expected 4.75")
				check(sample.referencedVertexCount==6,"duplicate indices/unreferenced vertex must not count")
				check(sample.belowFloorVertexCount==3,"only 3 skinned vertices below floor")
				check(absf(float(sample.surfaces[0].minimumY)-7.0)<0.0002,"static morph world min expected 7")
			instance.set_blend_shape_value(0,1.0)
			skeleton.set_bone_pose_position(0,Vector3(0,-1,0))
			await process_frame
			await RenderingServer.frame_post_draw
			var later: Dictionary = helper.sample()
			results.back()["later"] = later
			check(not later.has("error"),"later sample: %s" % later)
			if not later.has("error"):
				check(absf(float(later.minimumY)-3.0)<0.0002,"updated morph plus skin min expected 3")
			var filtered = Helper.new()
			check(filtered.initialize(model,5.0,"static").is_empty(),"static filter init")
			var filtered_sample: Dictionary = filtered.sample()
			results.back()["filtered"] = filtered_sample
			check(not filtered_sample.has("error") and filtered_sample.get("referencedVertexCount")==3,"filter excludes proxies and skinned surface")
			check(instance.mesh==mesh and instance.skin==skin and instance.transform.origin.y==3,"source preserved")
			check(mesh.surface_get_arrays(1)[Mesh.ARRAY_VERTEX][0].y==1,"bind positions preserved")
			var missing = Helper.new()
			check(not missing.initialize(model,5.0,"missing").is_empty(),"missing filter must fail")
		model.free()
	return results

func test_edges() -> Dictionary:
	var results := {}
	var model := Node3D.new()
	root.add_child(model)
	var instance := MeshInstance3D.new()
	instance.name = "Static"
	var mesh := ArrayMesh.new()
	var a := []
	a.resize(Mesh.ARRAY_MAX)
	a[Mesh.ARRAY_VERTEX] = PackedVector3Array([Vector3(0,-1,0),Vector3(1,0,0),Vector3(0,0,1)])
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES,a)
	instance.mesh = mesh
	model.add_child(instance)
	var plain = Helper.new()
	check(plain.initialize(model,0).is_empty(),"static no-indices initialize")
	results["plain"] = plain.sample()
	check(results.plain.get("referencedVertexCount")==3 and results.plain.get("belowFloorVertexCount")==1,"unindexed count")
	instance.position.y = 2
	results["moved"] = plain.sample()
	check(results.moved.get("minimumY")==1.0,"static updated global transform")
	instance.position.y = NAN
	results["nonfiniteTransform"] = plain.sample()
	check(results.nonfiniteTransform.has("error"),"reject nonfinite transform")
	instance.position.y = 0
	mesh.emit_changed()
	check(plain.sample().has("error"),"source mutation invalidates topology cache")
	var skeleton := Skeleton3D.new()
	skeleton.name = "Skeleton"
	skeleton.add_bone("root")
	model.add_child(skeleton)
	var skin := Skin.new()
	skin.add_named_bind("root",Transform3D.IDENTITY)
	a[Mesh.ARRAY_BONES] = PackedInt32Array([0,0,0,0,0,0,0,0,0,0,0,0])
	a[Mesh.ARRAY_WEIGHTS] = PackedFloat32Array([1,0,0,0,1,0,0,0,1,0,0,0])
	var skinned := ArrayMesh.new()
	skinned.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES,a)
	instance.mesh = skinned
	instance.skin = skin
	instance.skeleton = instance.get_path_to(skeleton)
	skeleton.set_bone_pose_position(0,Vector3(0,-0.5,0))
	await process_frame
	await RenderingServer.frame_post_draw
	var skin_helper = Helper.new()
	check(skin_helper.initialize(model,0).is_empty(),"plain skin initialize")
	results["skin"] = skin_helper.sample()
	check(results.skin.get("minimumY")==-1.5,"plain native skin pose")
	# Preserve the 8-influence format and combine two moving bones, including
	# an influence beyond the first four slots.
	skeleton.add_bone("other")
	skeleton.set_bone_pose_position(1, Vector3(0, -2, 0))
	skeleton.set_bone_pose_rotation(1, Quaternion(Vector3(0, 0, 1), PI / 2))
	var eight_skin := Skin.new()
	eight_skin.add_named_bind("root", Transform3D.IDENTITY)
	eight_skin.add_named_bind("other", Transform3D(Basis.IDENTITY, Vector3(1, 0, 0)))
	var eight_arrays := a.duplicate(true)
	var eight_bones := PackedInt32Array()
	var eight_weights := PackedFloat32Array()
	for vertex in range(3):
		eight_bones.append_array(PackedInt32Array([0, 0, 0, 0, 1, 0, 0, 0]))
		eight_weights.append_array(PackedFloat32Array([0.25, 0, 0, 0, 0.75, 0, 0, 0]))
	eight_arrays[Mesh.ARRAY_BONES] = eight_bones
	eight_arrays[Mesh.ARRAY_WEIGHTS] = eight_weights
	var eight_mesh := ArrayMesh.new()
	eight_mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, eight_arrays, [], {}, Mesh.ARRAY_FLAG_USE_8_BONE_WEIGHTS)
	var eight_material := StandardMaterial3D.new()
	eight_material.resource_name = "EightInfluences"
	eight_mesh.surface_set_material(0, eight_material)
	var eight_instance := MeshInstance3D.new()
	eight_instance.mesh = eight_mesh
	eight_instance.skin = eight_skin
	model.add_child(eight_instance)
	eight_instance.skeleton = eight_instance.get_path_to(skeleton)
	var eight_helper = Helper.new()
	check(eight_helper.initialize(model, 0, "EightInfluences").is_empty(), "8-influence initialization")
	await process_frame
	await RenderingServer.frame_post_draw
	results["eightInfluences"] = eight_helper.sample()
	check(absf(float(results.eightInfluences.get("minimumY", INF)) + 1.125) < 0.0002, "8-influence weighted pose with rotation and inverse bind")
	eight_instance.free()
	var lines := ArrayMesh.new()
	a[Mesh.ARRAY_INDEX] = PackedInt32Array([0,1])
	lines.add_surface_from_arrays(Mesh.PRIMITIVE_LINES,a)
	instance.mesh = lines
	var unsupported = Helper.new()
	results["nontriangleSkin"] = unsupported.initialize(model,0)
	check("triangles" in results.nontriangleSkin,"explicit nontriangle skin rejection")
	instance.mesh = skinned
	instance.skeleton = NodePath("missing")
	var missing = Helper.new()
	results["missingSkeleton"] = missing.initialize(model,0)
	check("registered skin" in results.missingSkeleton,"missing skeleton rejection")
	instance.skeleton = instance.get_path_to(skeleton)
	var invalid_skin := Skin.new()
	invalid_skin.add_named_bind("missing",Transform3D.IDENTITY)
	instance.skin = invalid_skin
	var invalid = Helper.new()
	results["invalidBind"] = invalid.initialize(model,0)
	check("invalid bone binding" in results.invalidBind,"invalid bind name rejection")
	model.free()
	return results

func run() -> void:
	var morphs := await test_morph_skin()
	var edges := await test_edges()
	var file := FileAccess.open("res://result.json", FileAccess.WRITE)
	file.store_string(JSON.stringify({"failures": failures, "morphSkin": morphs, "edgeCases": edges,
		"renderer": RenderingServer.get_current_rendering_method(),
		"adapter": RenderingServer.get_video_adapter_name()}, "  ")+"\n")
	print(JSON.stringify({"failures": failures}))
	quit(0 if failures.is_empty() else 2)

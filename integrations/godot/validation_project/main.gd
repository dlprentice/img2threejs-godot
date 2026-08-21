extends Node3D

const ASSET_SCENE := "res://imports/current/asset.glb"
const MANIFEST_PATH := "res://imports/current/asset_manifest.json"
const EVIDENCE_DIRECTORY := "res://evidence/current"
const SCREENSHOT_PATH := EVIDENCE_DIRECTORY + "/rts.png"
const REPORT_PATH := EVIDENCE_DIRECTORY + "/godot_validation.json"

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


func _collect_nodes(node: Node, names: Dictionary) -> void:
	var node_name := String(node.name)
	if names.has(node_name):
		failures.append("duplicate imported node name: %s" % node_name)
	names[node_name] = node
	if node is MeshInstance3D:
		mesh_count += 1
	if node is Node3D and node_name.ends_with("-lod1"):
		node.visible = false
		lod1_hidden_count += 1
	for child in node.get_children():
		_collect_nodes(child, names)


func _material(color: Color, metallic: float, roughness: float) -> StandardMaterial3D:
	var result := StandardMaterial3D.new()
	result.albedo_color = color
	result.metallic = metallic
	result.roughness = roughness
	return result


func _add_stage() -> Camera3D:
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
	return camera


func _image_metrics(image: Image) -> Dictionary:
	var minimum_luma := 1.0
	var maximum_luma := 0.0
	var foreground_samples := 0
	var total_samples := 0
	for y in range(0, image.get_height(), 8):
		for x in range(0, image.get_width(), 8):
			var pixel := image.get_pixel(x, y)
			var luma := pixel.r * 0.2126 + pixel.g * 0.7152 + pixel.b * 0.0722
			minimum_luma = min(minimum_luma, luma)
			maximum_luma = max(maximum_luma, luma)
			if luma > 0.08:
				foreground_samples += 1
			total_samples += 1
	return {
		"minimumLuma": minimum_luma,
		"maximumLuma": maximum_luma,
		"lumaRange": maximum_luma - minimum_luma,
		"foregroundRatio": float(foreground_samples) / float(max(total_samples, 1)),
	}


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
	var dimensions: Array = contract.get("dimensions", [])
	if dimensions.size() != 3:
		failures.append("collision dimensions are invalid")
		return {}
	var body := StaticBody3D.new()
	body.name = "ManifestCollisionBody"
	names[parent_name].add_child(body)
	var shape_node := CollisionShape3D.new()
	shape_node.name = String(contract.get("id", "manifest-collision"))
	var box := BoxShape3D.new()
	box.size = Vector3(float(dimensions[0]), float(dimensions[1]), float(dimensions[2]))
	shape_node.shape = box
	var translation: Array = contract.get("transform", {}).get("translation", [0.0, 0.0, 0.0])
	shape_node.position = Vector3(float(translation[0]), float(translation[1]), float(translation[2]))
	body.add_child(shape_node)
	return {"id": String(contract.get("id", "")), "dimensions": dimensions}


func _write_report(report: Dictionary) -> void:
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(EVIDENCE_DIRECTORY))
	var file := FileAccess.open(REPORT_PATH, FileAccess.WRITE)
	if file == null:
		push_error("cannot write validation report")
		return
	file.store_string(JSON.stringify(report, "  ") + "\n")


func _finish_failure(message: String) -> void:
	failures.append(message)
	_write_report({"status": "fail", "failures": failures, "engineVersion": Engine.get_version_info().get("string", "unknown")})
	for failure in failures:
		push_error(failure)
	get_tree().quit(2)


func _run_validation() -> void:
	var manifest := _read_json(MANIFEST_PATH)
	if manifest.is_empty():
		_finish_failure("manifest could not be loaded")
		return
	var packed: Resource = load(ASSET_SCENE)
	if not packed is PackedScene:
		_finish_failure("GLB did not import as PackedScene")
		return
	var model: Node = packed.instantiate()
	model.name = "ImportedVehicle"
	add_child(model)
	var names: Dictionary = {}
	_collect_nodes(model, names)
	for required_name in ["hull", "turret", "weapon", "turret-pivot", "primary-weapon", "muzzle-vfx", "hull-collision"]:
		if not names.has(required_name):
			failures.append("required imported node is missing: %s" % required_name)
	var expected_mesh_count := int(manifest.get("meshNodes", []).size())
	if mesh_count != expected_mesh_count:
		failures.append("imported mesh count %d does not match manifest %d" % [mesh_count, expected_mesh_count])
	var expected_lod1 := 0
	for mesh_node in manifest.get("meshNodes", []):
		if int(mesh_node.get("lodLevel", -1)) == 1:
			expected_lod1 += 1
	if lod1_hidden_count != expected_lod1:
		failures.append("hidden LOD1 count %d does not match manifest %d" % [lod1_hidden_count, expected_lod1])
	var collision_result := _add_manifest_collision(manifest, names)
	_add_stage()
	if not failures.is_empty():
		_finish_failure("technical validation failed before rendering")
		return

	for _warmup_frame in range(60):
		await get_tree().process_frame
	var cpu_frame_samples: Array[float] = []
	for _sample_frame in range(30):
		await get_tree().process_frame
		await RenderingServer.frame_post_draw
		cpu_frame_samples.append(Performance.get_monitor(Performance.TIME_PROCESS) * 1000.0)
	var started := Time.get_ticks_usec()
	await get_tree().process_frame
	await RenderingServer.frame_post_draw
	var timing_metrics := _render_timing_metrics(cpu_frame_samples)
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(EVIDENCE_DIRECTORY))
	var image := get_viewport().get_texture().get_image()
	if image.is_empty():
		_finish_failure("viewport screenshot is empty")
		return
	var image_metrics := _image_metrics(image)
	if float(image_metrics["lumaRange"]) < 0.03 or float(image_metrics["foregroundRatio"]) < 0.01:
		_finish_failure("viewport screenshot is blank or lacks visible foreground: %s" % JSON.stringify(image_metrics))
		return
	if image.save_png(SCREENSHOT_PATH) != OK:
		_finish_failure("viewport screenshot could not be saved")
		return
	var elapsed_ms := float(Time.get_ticks_usec() - started) / 1000.0
	var report := {
		"status": "pass",
		"engineVersion": Engine.get_version_info().get("string", "unknown"),
		"renderingDriver": RenderingServer.get_current_rendering_driver_name(),
		"videoAdapter": RenderingServer.get_video_adapter_name(),
		"meshCount": mesh_count,
		"hiddenLod1Count": lod1_hidden_count,
		"collision": collision_result,
		"requiredNodes": ["hull", "turret", "weapon", "turret-pivot", "primary-weapon", "muzzle-vfx", "hull-collision"],
		"drawCalls": RenderingServer.get_rendering_info(RenderingServer.RENDERING_INFO_TOTAL_DRAW_CALLS_IN_FRAME),
		"captureFrameMilliseconds": elapsed_ms,
		"cpuFrameMilliseconds": timing_metrics["cpuFrameMilliseconds"],
		"cpuFrameP95Milliseconds": timing_metrics["cpuFrameP95Milliseconds"],
		"cpuFrameSampleCount": timing_metrics["cpuFrameSampleCount"],
		"gpuFrameMilliseconds": timing_metrics["gpuFrameMilliseconds"],
		"renderCpuTimestampSpanMilliseconds": timing_metrics["renderCpuTimestampSpanMilliseconds"],
		"gpuTimestampCount": timing_metrics["gpuTimestampCount"],
		"gpuTimingStatus": "MEASURED" if timing_metrics["gpuFrameMilliseconds"] != null else "UNAVAILABLE_IN_OFFICIAL_RUNTIME",
		"imageMetrics": image_metrics,
		"screenshot": "rts.png",
		"failures": [],
	}
	_write_report(report)
	print(JSON.stringify(report))
	get_tree().quit(0)

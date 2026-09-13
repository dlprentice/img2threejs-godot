extends Node3D

const DIMENSIONS := Vector2i(1280, 720)
var request: Dictionary
var record: Dictionary
var players: Array[AnimationPlayer] = []
var skeletons: Array[Skeleton3D] = []
var model: Node3D
var camera: Camera3D
var caption: Label
var followed_skeleton: Skeleton3D
var followed_bone := -1
var initial_follow_position := Vector3.ZERO


func _ready() -> void:
	_run.call_deferred()


func _write_record() -> void:
	var file := FileAccess.open(String(request.output).path_join("preview.json"), FileAccess.WRITE)
	if file == null:
		push_error("Cannot write preview.json")
		get_tree().quit(2)
		return
	file.store_string(JSON.stringify(record, "  ") + "\n")


func _fail(message: String) -> void:
	record["status"] = "failed"
	record["error"] = message
	_write_record()
	push_error(message)
	get_tree().quit(2)


func _collect(node: Node) -> void:
	if node is AnimationPlayer:
		players.append(node)
		# Imported autoplay never advances a clip between requested sample times.
		node.stop()
		node.callback_mode_process = AnimationMixer.ANIMATION_CALLBACK_MODE_PROCESS_MANUAL
	if node is Skeleton3D:
		skeletons.append(node)
	for child in node.get_children():
		_collect(child)


func _vec(value: Array) -> Vector3:
	return Vector3(float(value[0]), float(value[1]), float(value[2]))


func _material(color: Color) -> StandardMaterial3D:
	var material := StandardMaterial3D.new()
	material.albedo_color = color
	material.roughness = 0.85
	return material


func _stage() -> void:
	var environment := WorldEnvironment.new()
	environment.environment = Environment.new()
	environment.environment.background_mode = Environment.BG_COLOR
	environment.environment.background_color = Color(0.07, 0.085, 0.11)
	environment.environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	environment.environment.ambient_light_color = Color(0.8, 0.86, 1.0)
	environment.environment.ambient_light_energy = 0.65
	add_child(environment)
	var light := DirectionalLight3D.new()
	light.rotation_degrees = Vector3(-50, -30, 0)
	light.light_energy = 1.6
	light.shadow_enabled = true
	add_child(light)
	var floor := MeshInstance3D.new()
	var plane := PlaneMesh.new()
	plane.size = Vector2(200, 200)
	floor.mesh = plane
	floor.material_override = _material(Color(0.18, 0.20, 0.23))
	floor.position.y = -0.005
	add_child(floor)
	var grid := MeshInstance3D.new()
	var lines := ImmediateMesh.new()
	var grid_material := _material(Color(0.35, 0.38, 0.42))
	grid_material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	lines.surface_begin(Mesh.PRIMITIVE_LINES, grid_material)
	for index in range(-100, 101):
		lines.surface_add_vertex(Vector3(index, 0, -100))
		lines.surface_add_vertex(Vector3(index, 0, 100))
		lines.surface_add_vertex(Vector3(-100, 0, index))
		lines.surface_add_vertex(Vector3(100, 0, index))
	lines.surface_end()
	grid.mesh = lines
	add_child(grid)
	camera = Camera3D.new()
	camera.projection = Camera3D.PROJECTION_ORTHOGONAL
	camera.keep_aspect = Camera3D.KEEP_HEIGHT
	camera.size = float(request.orthoSize)
	camera.near = 0.01
	camera.far = 1000.0
	add_child(camera)
	camera.current = true
	var layer := CanvasLayer.new()
	add_child(layer)
	var background := ColorRect.new()
	background.color = Color(0, 0, 0, 0.7)
	background.position = Vector2(12, 12)
	background.size = Vector2(1256, 66)
	layer.add_child(background)
	caption = Label.new()
	caption.position = Vector2(22, 18)
	caption.add_theme_font_size_override("font_size", 18)
	layer.add_child(caption)


func _bone_position() -> Vector3:
	return followed_skeleton.global_transform * followed_skeleton.get_bone_global_pose(followed_bone).origin


func _set_camera() -> Vector3:
	var target := _vec(request.cameraCenter)
	if followed_skeleton != null:
		target += _bone_position() - initial_follow_position
	camera.position = target + _vec(request.cameraOffset)
	camera.look_at(target, Vector3.UP)
	return target


func _select_follow() -> bool:
	if request.followBone == null:
		return true
	var matches: Array[Skeleton3D] = []
	for skeleton in skeletons:
		if request.skeletonPath != null and String(model.get_path_to(skeleton)) != String(request.skeletonPath):
			continue
		if skeleton.find_bone(String(request.followBone)) >= 0:
			matches.append(skeleton)
	if matches.size() != 1:
		_fail("Follow bone must match exactly one skeleton; select --skeleton-path from the clip listing")
		return false
	followed_skeleton = matches[0]
	followed_bone = followed_skeleton.find_bone(String(request.followBone))
	return true


func _run() -> void:
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string("res://request.json"))
	if not parsed is Dictionary:
		push_error("Missing or invalid request.json")
		get_tree().quit(2)
		return
	request = parsed
	if FileAccess.file_exists(String(request.output).path_join("preview.json")):
		push_error("Existing preview.json is never overwritten; use a fresh output directory")
		get_tree().quit(2)
		return
	record = {
		"status": "running", "source": request.source, "sourceSha256": request.sourceSha256,
		"engineVersion": Engine.get_version_info().string,
		"renderingMethod": RenderingServer.get_current_rendering_method(),
		"renderingDriver": RenderingServer.get_current_rendering_driver_name(),
		"videoAdapter": RenderingServer.get_video_adapter_name(),
		"dimensions": [DIMENSIONS.x, DIMENSIONS.y], "players": [], "skeletons": [], "frames": [],
	}
	if FileAccess.get_sha256("res://source.glb") != String(request.sourceSha256):
		_fail("Source copy hash differs from request")
		return
	var document := GLTFDocument.new()
	var state := GLTFState.new()
	var flags: int = GLTFDocument.IMPORT_FLAG_GENERATE_TANGENT_ARRAYS | GLTFDocument.IMPORT_FLAG_USE_NAMED_SKIN_BINDS
	var error := document.append_from_file("res://source.glb", state, flags)
	if error != OK:
		_fail("GLTFDocument load failed: %s" % error)
		return
	model = document.generate_scene(state)
	if model == null:
		_fail("GLTFDocument did not generate a scene")
		return
	add_child(model)
	_collect(model)
	for player in players:
		var clips: Array = []
		for name in player.get_animation_list():
			var animation := player.get_animation(name)
			clips.append({"name": name, "durationSeconds": animation.length, "loopMode": animation.loop_mode})
		record.players.append({"path": String(model.get_path_to(player)), "clips": clips})
	for skeleton in skeletons:
		var bones: Array = []
		for index in range(skeleton.get_bone_count()):
			bones.append(skeleton.get_bone_name(index))
		record.skeletons.append({"path": String(model.get_path_to(skeleton)), "bones": bones})
	if request.animation == null:
		record["mode"] = "list"
		record.status = "complete"
		_write_record()
		get_tree().quit()
		return
	var candidates: Array[AnimationPlayer] = []
	for player in players:
		if request.playerPath == null or String(model.get_path_to(player)) == String(request.playerPath):
			candidates.append(player)
	if candidates.size() != 1:
		_fail("Select exactly one AnimationPlayer with --player-path; see players in this record")
		return
	var selected := candidates[0]
	var clip_name := String(request.animation)
	if not selected.has_animation(clip_name):
		_fail("Animation does not exist on the selected player: %s" % clip_name)
		return
	var clip := selected.get_animation(clip_name)
	record["sourceLoopMode"] = clip.loop_mode
	record["loopRequest"] = request.loop
	if request.loop == "linear":
		clip.loop_mode = Animation.LOOP_LINEAR
	elif request.loop == "ping-pong":
		clip.loop_mode = Animation.LOOP_PINGPONG
	if clip.length <= 0.0:
		_fail("Animation duration must be positive")
		return
	if not _select_follow():
		return
	_stage()
	selected.play(clip_name)
	selected.advance(0.0)
	# Allow Skeleton3D/render updates to settle before measuring frame zero.
	await get_tree().process_frame
	if followed_skeleton != null:
		initial_follow_position = _bone_position()
	record["mode"] = "capture"
	record["animation"] = clip_name
	record["playerPath"] = String(model.get_path_to(selected))
	record["clipDurationSeconds"] = clip.length
	record["loopMode"] = clip.loop_mode
	record["loopBehavior"] = ["hold final pose", "linear wrap", "ping-pong"][clip.loop_mode]
	record["fps"] = request.fps
	record["requestedDurationSeconds"] = request.durationSeconds
	record["outputDurationSeconds"] = float(request.frameCount) / float(request.fps)
	record["camera"] = {
		"mode": "follow-bone-displacement" if followed_skeleton != null else "fixed",
		"center": request.cameraCenter, "offset": request.cameraOffset,
		"orthographicVerticalSize": request.orthoSize, "followBone": request.followBone,
		"skeletonPath": String(model.get_path_to(followed_skeleton)) if followed_skeleton != null else null,
	}
	record["floor"] = {"worldY": -0.005, "gridSpacing": 1.0, "extent": 100.0}
	for index in range(int(request.frameCount)):
		if index > 0:
			selected.advance(1.0 / float(request.fps))
		await get_tree().process_frame
		var target := _set_camera()
		var actual_time := selected.current_animation_position
		var output_time := float(index) / float(request.fps)
		var camera_label := "Camera follows " + String(request.followBone) if followed_skeleton != null else "Fixed camera"
		caption.text = "%s | clip %.4f / %.4f s | output %.4f s | frame %d\n%s | loop: %s | grid: 1 source unit" % [
			clip_name, actual_time, clip.length, output_time, index, camera_label, request.loop]
		await RenderingServer.frame_post_draw
		var image := get_viewport().get_texture().get_image()
		if image.is_empty() or image.get_size() != DIMENSIONS:
			_fail("Capture did not produce the fixed 1280x720 viewport")
			return
		var filename := "frame-%05d.png" % index
		if FileAccess.file_exists(String(request.output).path_join(filename)):
			_fail("Existing frame is never overwritten: %s" % filename)
			return
		if image.save_png(String(request.output).path_join(filename)) != OK:
			_fail("Cannot save frame: %s" % filename)
			return
		var saved := Image.new()
		if saved.load(String(request.output).path_join(filename)) != OK or saved.get_size() != DIMENSIONS:
			_fail("Saved PNG cannot be decoded at the requested dimensions: %s" % filename)
			return
		record.frames.append({
			"file": filename, "dimensions": [image.get_width(), image.get_height()],
			"sha256": FileAccess.get_sha256(String(request.output).path_join(filename)),
			"outputTimeSeconds": output_time, "animationTimeSeconds": actual_time,
			"playing": selected.is_playing(), "cameraTarget": [target.x, target.y, target.z],
		})
	record.status = "complete"
	_write_record()
	get_tree().quit()

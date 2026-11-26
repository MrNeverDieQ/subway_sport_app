[app]
title = 地铁健身
package.name = subwaysport
package.domain = com.subwaysport
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,otf,ttf,mp4,mp3,wav,json
source.include_patterns = audio/*,audio/**/*,fonts/*
source.exclude_dirs = .venv, tests, bin, .buildozer, .github, video/_drafts, audio/_archive
source.exclude_patterns = AGENT_NOTES.md, Dockerfile, requirements.txt
version = 1.0

requirements = python3,kivy==2.3.0,ffpyplayer

# 训练中的计时与放音跑在前台服务进程里（service/main.py），锁屏/切后台不受 Kivy 主循环挂起影响
# 类名由 p4a 生成为 <package>.ServiceWorkout，screens/workout_session.py 按这个名字启动它
services = Workout:service/main.py:foreground
# 注意：android.api 升到 34 时前台服务必须声明 foregroundServiceType（mediaPlayback）并加对应权限，否则 startForeground 抛 SecurityException

orientation = portrait
fullscreen = 1

android.permissions = VIBRATE,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,FOREGROUND_SERVICE,WAKE_LOCK,POST_NOTIFICATIONS
android.api = 33
android.minapi = 21
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True
android.ndk = 25b

# python-for-android 固定到 v2024.01.21（master 自 2026-05 起是 v2026.05.09：ffmpeg 8.0.1 删掉了 libavcodec/avfft.h，
# 而 ffpyplayer 4.5.x 仍然 include 它，ffpyplayer 编不过，2026-11-26 CI 实测失败）。
# 2024.01.21 = ffmpeg 4.3.1 + ffpyplayer 4.3.2 + Python 3.11.5 + NDK 25b，2026-03 CI 验证过能出包。
# 想升 p4a 时先确认 ffpyplayer 支持 FFmpeg 8（或 p4a 的 ffpyplayer 配方打了补丁）。
p4a.branch = master
p4a.commit = 957a3e5f8c270f7aa648ba185e5a68c1077a798d

[buildozer]
log_level = 2

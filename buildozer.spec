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

[buildozer]
log_level = 2

[app]
title = 地铁健身
package.name = subwaysport
package.domain = com.subwaysport
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,otf,ttf,mp4,mp3,wav
source.include_patterns = audio/*,audio/**/*,fonts/*,video/*
source.exclude_dirs = audio_backup,tests,__pycache__,.git
version = 1.0

requirements = python3,kivy==2.3.0,ffpyplayer

services = Workout:service/workout_service.py:foreground

orientation = portrait
fullscreen = 1

android.permissions = VIBRATE,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,FOREGROUND_SERVICE
android.api = 33
android.minapi = 21
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True
android.wakelock = True

[buildozer]
log_level = 2

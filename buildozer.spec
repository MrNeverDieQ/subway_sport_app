[app]
title = 地铁健身
package.name = subwaysport
package.domain = com.subwaysport
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,otf,ttf,mp4,mp3,wav
source.include_patterns = audio/*,audio/**/*,fonts/*,video/*
version = 1.0

requirements = python3,kivy==2.3.0,ffpyplayer

orientation = portrait
fullscreen = 1

android.permissions = VIBRATE,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE
android.api = 33
android.minapi = 21
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True

[buildozer]
log_level = 2

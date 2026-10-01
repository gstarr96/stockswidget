; AI Stock News - appearance and behavior.
; API keys and AI settings are NOT here: right-click the widget > Edit settings.
; Refresh the skin after editing this file.

[Variables]
; ----- Behavior -----
; Command used to run Python. "py" is the launcher installed by python.org.
; Use "python" for Microsoft Store installs, or the full path to python.exe.
Python=py
; Minutes between data refreshes (prices, charts, news).
RefreshMinutes=15
; Seconds each story stays on screen. Hovering the widget pauses the carousel.
SlideSeconds=12
; Seconds between Watchlist price refreshes (Yahoo Finance only, no AI usage).
WatchRefreshSeconds=60

; ----- Colors (R,G,B or R,G,B,Alpha) -----
ColorBackground=17,19,26,235
ColorCard=255,255,255,10
ColorDivider=255,255,255,22
ColorText=236,238,243
ColorBody=196,201,212
ColorDim=138,145,160
ColorAccent=110,150,255
; Chart and change colors must be R,G,B only (the script adds transparency).
ColorUp=38,194,129
ColorDown=239,83,80
ColorFlat=138,145,160
ColorWarn=240,180,60

; ----- Fonts -----
FontFace=Segoe UI

; ----- Layout (pixels) -----
Padding=16
StoryW=410
StoryChartH=62
IndexW=202
IndexChartW=182
IndexChartH=28
CardH=78
CardGap=8

; ----- Watchlist layout (pixels) -----
WatchColumns=3
WatchTileW=150
WatchTileH=76
WatchGap=8

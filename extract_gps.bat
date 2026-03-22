@echo off
echo Extracting GPX data with fixed timestamps...
echo.

for %%f in (*.mp4) do (
    echo Processing: %%f
    exiftool -d "%%Y-%%m-%%dT%%H:%%M:%%SZ" -ee -p gpx.fmt "%%f" > "%%~nf.gpx"
)

echo.
echo All done! You can now view speeds or compress your videos.
pause
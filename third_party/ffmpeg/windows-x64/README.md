# FFmpeg para ColpoCap (Windows x64)

Esta carpeta es la ubicación estable del ejecutable que utiliza ColpoCap:

```text
third_party/ffmpeg/windows-x64/ffmpeg.exe
```

El binario no se guarda en Git por su tamaño. En Windows, instálelo desde la
raíz del proyecto con:

```powershell
.\scripts\install_ffmpeg_windows.ps1
```

El instalador descarga una versión fijada de `essentials_build` para Windows
x64, valida el checksum SHA-256 antes de extraerla, comprueba `-version` y el
soporte DirectShow (`dshow`), y conserva junto al ejecutable la información de
origen y los avisos de licencia provistos por el paquete.

Para reemplazar una copia existente, ejecute el script con `-Force`.

Orden de selección en la aplicación:

1. ruta entregada explícitamente al código;
2. variable de entorno `COLPOCAP_FFMPEG`;
3. este binario incluido en el proyecto;
4. `ffmpeg` disponible en el `PATH` del sistema.

La compilación distribuida por Gyan está licenciada bajo GPLv3 porque incorpora
componentes GPL, entre ellos `libx264`. Si se redistribuye ColpoCap junto con el
binario, deben conservarse los avisos de licencia y la información de código
fuente correspondientes. Consulte `SOURCE.txt` y el archivo `LICENSE` que crea
el instalador.

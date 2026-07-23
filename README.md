# ColpoCap MVP

Estación desktop de captura colposcópica para Windows 10/11. Consulta una DICOM Modality Worklist, asocia el procedimiento elegido con una grabación MP4 local, muestra la cámara en vivo, permite capturar múltiples imágenes y las envía al PACS como una única serie DICOM al finalizar el estudio.

El objetivo de esta versión es validar interoperabilidad, trazabilidad y operación segura del flujo básico. La interfaz es deliberadamente simple.

## Alcance exacto

Flujo obligatorio implementado:

```text
menú → MWL C-FIND → selección → cámara + MP4/H.264 local
     → snapshots JPEG en vivo → finalizar
     → serie DICOM VL Endoscopic Image → C-ECHO → lote C-STORE PACS
```

Incluye:

- consulta MWL por fecha, PatientName, PatientID y AccessionNumber;
- tabla y selección explícita del estudio;
- captura FFmpeg/DirectShow en Windows y diagnóstico de dispositivos;
- preview en vivo obtenido del mismo proceso FFmpeg que graba el MP4;
- captura de múltiples snapshots del cuadro exacto mostrado al operador;
- DICOM RGB Explicit VR Little Endian sin compresión, con una serie común e instancias numeradas;
- validación del DICOM por relectura antes del envío;
- C-ECHO y envío de todas las instancias mediante una sola asociación C-STORE, con registro individual de cada status DICOM;
- SQLite local con estudios, capturas y todos los intentos de exportación;
- reintento manual de pendientes o fallidos;
- log rotativo en `logs/app.log` y log visible en la UI.

No incluye autenticación, informes, firma, HL7, DICOMweb, instalador ni video DICOM completo. `create_video_endoscopic()` existe únicamente como interfaz futura y lanza `NotImplementedError`: no encapsula MP4/H.264 de forma ficticia.

## Requisitos

- Windows 10/11 para el destino inicial;
- Python 3.11 o superior de 64 bits;
- FFmpeg x64 incluido en `third_party/ffmpeg/windows-x64` mediante el instalador del proyecto;
- capturadora UVC/HDMI expuesta a FFmpeg/DirectShow;
- conectividad TCP hacia MWL y PACS.

Dependencias Python: PySide6, pydicom, pynetdicom, Pillow y pytest. OpenCV no es necesario.

## Instalación en Windows

Desde PowerShell, en la raíz del repositorio:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item config\settings.example.json config\settings.json
.\scripts\install_ffmpeg_windows.ps1
```

El último comando descarga la versión de FFmpeg fijada por el proyecto, valida
su checksum SHA-256 y comprueba que incluya DirectShow. El ejecutable queda en:

```powershell
.\third_party\ffmpeg\windows-x64\ffmpeg.exe
```

No es necesario agregarlo al `PATH`. ColpoCap elige primero una ruta explícita,
luego `COLPOCAP_FFMPEG`, después el binario incluido y, solamente si este no
existe, intenta usar el `PATH` del sistema. Tanto la grabación como la creación
de snapshots comparten este mismo mecanismo.

Para listar la cámara y verificar qué nombre debe copiarse exactamente a
`video.device_name`, ejecute la aplicación, abra “Configurar y probar conexiones”
y use “Detectar dispositivos de video”.
El diálogo muestra el ejecutable y la versión seleccionados, el comando y toda
la salida de DirectShow. También puede ejecutar manualmente:

```powershell
& .\third_party\ffmpeg\windows-x64\ffmpeg.exe -hide_banner -list_devices true -f dshow -i dummy
```

Si ya existe un binario en la carpeta y necesita reinstalarlo:

```powershell
.\scripts\install_ffmpeg_windows.ps1 -Force
```

## Configuración

La aplicación carga `config/settings.json` por defecto. El repositorio entrega solamente `config/settings.example.json` para evitar versionar configuración real. Si el archivo no existe o es inválido, el inicio se detiene con un mensaje claro.

```json
{
  "local_ae_title": "COLPOCAP_MVP",
  "worklist": {
    "ae_title": "COLPOCAP_WL",
    "host": "127.0.0.1",
    "port": 11112
  },
  "pacs": {
    "ae_title": "ORTHANC",
    "host": "127.0.0.1",
    "port": 4242
  },
  "video": {
    "device_name": "",
    "resolution": "1920x1080",
    "fps": 30,
    "bitrate": "8M"
  },
  "institution": {
    "name": "Instituto de Diagnóstico por Imágenes",
    "station_name": "COLPOSCOPY_CAPTURE_01",
    "manufacturer": "Custom",
    "manufacturer_model_name": "Colposcopy Capture MVP",
    "software_version": "0.1.0"
  },
  "storage": {
    "base_output_dir": "./output"
  }
}
```

Las rutas relativas de almacenamiento se resuelven respecto de la raíz del proyecto. No hay AE Titles, hosts, puertos, directorios clínicos ni dispositivos embebidos en el código. Los AE Titles se validan a un máximo de 16 caracteres.

`StationName` tiene VR DICOM SH (máximo 16 caracteres). El valor de ejemplo es más largo para conservar el requisito recibido; al generar DICOM se trunca con una advertencia explícita en UI y log. En producción conviene configurarlo directamente con 16 caracteres o menos.

También se puede indicar otra configuración:

```powershell
python -m app.main --config C:\ColpoCap\settings.json
```

## Ejecución y operación

```powershell
python -m app.main
```

1. En el menú principal, use “Configurar y probar conexiones” para editar Worklist, PACS y cámara, guardar los cambios y ejecutar C-ECHO.
2. Vuelva al menú y elija “Leer Worklist e iniciar estudio”.
3. Ajuste los filtros y pulse “Buscar”. La fecha actual se aplica por defecto.
4. Verifique una fila y pulse “Iniciar estudio seleccionado”.
5. En la pantalla de captura, pulse “Iniciar estudio y cámara”.
6. Cuando aparezca el video en vivo, pulse “Capturar snapshot” tantas veces como sea necesario. La galería confirma cada imagen.
7. Pulse “Finalizar y enviar al PACS”. ColpoCap detiene el MP4, genera toda la serie DICOM y envía las imágenes juntas.
8. Un envío fallido o parcial aparece en el menú principal y puede reintentarse sin reenviar las instancias ya aceptadas.

La UI impide iniciar sin estudio, capturar antes de recibir un frame y finalizar sin snapshots. Si la Worklist no entrega StudyInstanceUID, se genera uno y queda registrado localmente antes de capturar. Cada estudio usa un SeriesInstanceUID común y un SOPInstanceUID nuevo por snapshot.

## Archivos y trazabilidad

Por defecto:

```text
output/
├── colpocap.sqlite3
├── videos/
│   ├── <PatientID>_<Accession>_<fecha>_<uid>.mp4
│   └── <mismo_nombre>.ffmpeg.log
├── snapshots/
│   ├── <mismo_nombre>_snapshot_001_<id>.jpg
│   └── <mismo_nombre>_snapshot_002_<id>.jpg
└── dicom/
    ├── <mismo_nombre>_snapshot_001_<id>.dcm
    └── <mismo_nombre>_snapshot_002_<id>.dcm
logs/
└── app.log
```

Los componentes del nombre se sanitizan. SQLite conserva la ruta del MP4 y una fila por imagen en `capture_images`, aunque los objetos enviados al PACS sean las imágenes fijas. Cada intento C-STORE crea filas en `dicom_exports`, manteniendo imagen, status, destino, hora, respuesta y error.

El PixelData DICOM no está comprimido. Como el snapshot operativo llega codificado en JPEG, el objeto conserva correctamente `LossyImageCompression = 01` y el método JPEG: descomprimir los píxeles no borra el antecedente de compresión con pérdida.

Estados principales: `SELECTED`, `RECORDING`, `RECORDED`, `SNAPSHOT_CREATED`, `DICOM_CREATED`, `SENT` y `FAILED`.

## Servidor MWL local de desarrollo

El repositorio incluye un servidor DICOM Modality Worklist de laboratorio. Su
objetivo es probar exactamente el mismo C-FIND que después se dirigirá al MWL
del instituto; no reemplaza al RIS/MWL institucional ni debe usarse con
pacientes reales.

En una primera ventana de PowerShell, con el entorno virtual activado, inicie el
servidor:

```powershell
python -m app.dicom.mwl_server
```

Los parámetros predeterminados son:

```text
Called AE Title:  COLPOCAP_WL
Calling AE permitido: COLPOCAP_MVP
IP:               127.0.0.1
Puerto:           11112
Turnos:           config/mwl.sample.json
```

Configure `config/settings.json` con esos mismos valores en la sección
`worklist`. En una segunda ventana ejecute la aplicación:

```powershell
python -m app.main
```

Pruebe la Worklist desde Configuración y luego búsquela desde su pantalla. Las entradas que usan
`"scheduled_start_date": "TODAY"` adoptan automáticamente la fecha del día.
El servidor vuelve a leer `config/mwl.sample.json` en cada C-FIND, por lo que
los turnos se pueden editar sin reiniciarlo.

También se puede probar directamente con el `findscu` instalado por
`pynetdicom`:

```powershell
.\.venv\Scripts\findscu.exe -v -W -aet COLPOCAP_MVP -aec COLPOCAP_WL -k PatientID=PID-001 127.0.0.1 11112
```

Para usar otro archivo, puerto o AE Title:

```powershell
python -m app.dicom.mwl_server `
  --data C:\ColpoCap\turnos-prueba.json `
  --ae-title MWL_PRUEBA `
  --port 11113 `
  --allow-calling-ae COLPOCAP_MVP
```

El listener usa `127.0.0.1` de forma predeterminada para no exponer datos de
prueba a la red. Cuando se integre con el instituto, no se inicia este servidor:
se reemplazan `worklist.ae_title`, `worklist.host` y `worklist.port` por los
datos entregados por el área de sistemas.

## Prueba local con Orthanc como PACS

Orthanc usa por defecto AE Title `ORTHANC`, puerto DICOM `4242` y HTTP `8042`, según su [documentación de configuración](https://orthanc.uclouvain.be/book/users/configuration.html). En Windows, la [guía oficial](https://orthanc.uclouvain.be/book/users/quick-start-windows.html) explica el instalador y la ubicación de los archivos de configuración.

Para un entorno **exclusivamente local de desarrollo**, puede usar este fragmento de configuración y reiniciar Orthanc:

```json
{
  "Name": "ColpoCap Test PACS",
  "DicomServerEnabled": true,
  "DicomAet": "ORTHANC",
  "DicomPort": 4242,
  "HttpPort": 8042,
  "RemoteAccessAllowed": false,
  "AuthenticationEnabled": false
}
```

No exponga esta configuración sin autenticación fuera de `localhost`. Para una red clínica aplique las recomendaciones oficiales de [seguridad de Orthanc](https://orthanc.uclouvain.be/book/faq/security.html).

Configure ColpoCap así:

```json
"pacs": {
  "ae_title": "ORTHANC",
  "host": "127.0.0.1",
  "port": 4242
}
```

Después:

1. abra Orthanc Explorer 2 en `http://localhost:8042/ui/app/` (o la interfaz incluida por su distribución);
2. pulse “Probar PACS”; debe recibir `0x0000`;
3. complete el flujo y envíe la imagen;
4. verifique paciente, estudio, serie e instancia en Orthanc, especialmente PatientID, AccessionNumber y StudyInstanceUID.

Orthanc base se usa aquí solamente para C-ECHO y C-STORE. El servidor MWL de
desarrollo se ejecuta por separado en el puerto `11112`. Esta separación replica
mejor la instalación futura, donde el RIS/MWL y el PACS pueden tener AE Titles,
direcciones y puertos distintos.

## Tests

```powershell
python -m pytest
```

Los tests mínimos cubren:

- validez y no reutilización de UIDs;
- esquema SQLite, claves foráneas, pendientes e historial de reintentos;
- creación, relectura, metadata, transferencia y PixelData RGB del VL Endoscopic Image;
- servidor MWL JSON, filtros, C-ECHO y C-FIND real de extremo a extremo;
- garantía de que el camino de video DICOM no simula una implementación.

Los tests no necesitan PACS ni capturadora. La prueba DICOM de integración con Orthanc y la prueba física de DirectShow son manuales.

## Estructura

```text
app/
├── main.py
├── config.py
├── logging_config.py
├── ui/
│   ├── main_window.py
│   ├── worklist_view.py
│   ├── capture_view.py
│   └── workers.py
├── dicom/
│   ├── worklist_client.py
│   ├── store_client.py
│   ├── dicom_builder.py
│   └── uid.py
├── video/
│   ├── capture_manager.py
│   ├── ffmpeg_locator.py
│   ├── ffmpeg_manager.py
│   └── snapshot_manager.py
├── db/
│   ├── database.py
│   └── models.py
└── services/
    ├── study_service.py
    └── export_service.py
tests/
├── test_uid_generation.py
├── test_database.py
├── test_dicom_builder.py
└── test_dicom_networking.py
scripts/
└── install_ffmpeg_windows.ps1
third_party/ffmpeg/windows-x64/
├── README.md
└── ffmpeg.exe                   # instalado localmente; no versionado en Git
```

## Limitaciones técnicas

- No hay video DICOM. `Video Endoscopic Image Storage` requiere seleccionar y validar perfiles MPEG/H.264, transfer syntaxes, encapsulación, offsets y compatibilidad real del PACS. Una fase futura debe evaluar DCMTK, dcm4che u otra implementación especializada con archivos de conformidad y pruebas contra el PACS objetivo.
- El MP4/H.264 local no se envía al PACS y debe incluirse en la política institucional de retención, respaldo y recuperación.
- No hay Storage Commitment, MPPS ni reconciliación de pacientes. Un status C-STORE exitoso confirma aceptación de la instancia, no retención de largo plazo.
- La asociación DICOM del MVP no usa TLS.
- La Worklist puede no entregar StudyInstanceUID; el UID local generado mantiene coherencia entre la captura y la imagen, pero el flujo institucional debe validar la reconciliación posterior.
- El preview se entrega como JPEG a 10 fps para no bloquear la codificación del MP4; la resolución DICOM corresponde al frame entregado por FFmpeg.
- La base y los medios no están cifrados y el log no es un audit trail inmutable.

## Advertencias clínicas y regulatorias

Este repositorio es un MVP técnico, no un producto sanitario validado ni autorizado para diagnóstico. Antes de uso clínico se requieren, como mínimo: gestión de riesgos, ingeniería de usabilidad, ciberseguridad, control de acceso, identificación de operador, protección de datos personales, validación del hardware de captura, pruebas de interoperabilidad con la declaración de conformidad DICOM del PACS, respaldo/retención, monitoreo, procedimientos ante downtime y validación regulatoria aplicable.

No use datos reales de pacientes en desarrollo. Valide siempre en pantalla y en el PACS que PatientID, AccessionNumber y StudyInstanceUID corresponden a la persona y procedimiento seleccionados.

## Próximos pasos sugeridos

1. pruebas de integración automatizadas con Orthanc y un MWL SCP de laboratorio;
2. colas de reintento automáticas con backoff y estado de red;
3. usuarios, roles y audit trail protegido;
4. eliminación y reordenamiento de snapshots antes de finalizar;
5. MPPS/Storage Commitment y reconciliación controlada;
6. cifrado, hardening y despliegue administrado;
7. evaluación separada y experimental de Video Endoscopic Image Storage;
8. HL7/DICOMweb y soporte de otras modalidades.

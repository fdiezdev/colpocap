# Logo de ElectroCap

Coloque el logo principal en esta ruta exacta:

```text
assets/electrocap_logo.png
```

La pantalla principal lo carga al iniciar. Se recomienda un PNG con fondo
transparente, proporción horizontal y al menos 960 × 290 píxeles. Si el archivo
no existe o no puede leerse, la interfaz muestra el nombre ElectroCap como
respaldo.

## Ícono de la aplicación

Para cambiar el ícono de la ventana y la barra de tareas, coloque un PNG
cuadrado en:

```text
assets/electrocap_icon.png
```

Se recomienda una imagen de 512 × 512 píxeles con fondo transparente. Si ese
archivo no existe, ElectroCap usa el logo principal como respaldo.

Al generar un ejecutable de Windows, el ícono del archivo `.exe` se define
durante el empaquetado y conviene usar además un archivo ICO multirresolución:

```text
assets/electrocap_icon.ico
```

Por ejemplo, con PyInstaller se pasa
`--icon assets/electrocap_icon.ico`. Después de cambiar cualquiera de estos
archivos, reinicie la aplicación.

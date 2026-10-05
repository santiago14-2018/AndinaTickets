# Instalar AndinaTickets en una PC con Windows

Guía para armar el entorno de desarrollo en una PC nueva con Windows 10 u 11, y para pasarle
los datos de otra PC. Los comandos van en **PowerShell**.

Versiones con las que funciona hoy (02/10/2026): WSL 2.7, Docker 29.8, Docker Compose 5.5,
Git 2.54. Versiones más nuevas deberían andar igual.

## 1. Requisitos de la PC

- Windows 10 (22H2) u 11, con las actualizaciones al día.
- 16 GB de RAM recomendados (8 GB como mínimo) y 30 GB libres en disco.
- Virtualización activada en el BIOS (suele llamarse "Intel VT-x", "AMD-V" o "SVM"). Para
  verificarlo: Administrador de tareas → Rendimiento → CPU → "Virtualización: Habilitado".

## 2. WSL (Linux dentro de Windows)

Docker lo necesita. Abrí PowerShell **como administrador** (clic derecho → Ejecutar como
administrador):

```powershell
wsl --install
```

Reiniciá la PC cuando termine. Para comprobar:

```powershell
wsl --version
```

## 3. Docker Desktop

1. Descargalo de https://www.docker.com/products/docker-desktop/ e instalalo con la opción
   **Use WSL 2** marcada.
2. Abrilo y aceptá los términos.
3. En **Settings → General**, marcá **Start Docker Desktop when you sign in to your
   computer**. Así, cuando la PC arranca, el sistema vuelve a levantarse solo.

Para comprobar (PowerShell común, sin administrador):

```powershell
docker version
docker compose version
```

## 4. Git

1. Descargalo de https://git-scm.com/download/win e instalalo con las opciones que vienen
   marcadas.
2. Configurá tu nombre y tu email (los mismos que en la otra PC; ahí se ven con
   `git config --global user.name` y `git config --global user.email`):

```powershell
git config --global user.name "santiago14-2018"
git config --global user.email "tu-email@ejemplo.com"
```

## 5. Bajar el código

```powershell
mkdir D:\Ticketing
git clone -c core.autocrlf=input https://github.com/santiago14-2018/AndinaTickets.git D:\Ticketing\AndinaTickets
cd D:\Ticketing\AndinaTickets
```

`-c core.autocrlf=input` deja los archivos con saltos de línea LF, los de Linux, que es
donde corre el sistema. Si la PC no tiene disco D:, usá otra carpeta y reemplazala en los
comandos que siguen.

Agregá pretix como remoto de solo lectura, para traer sus actualizaciones (ver `ANDINA.md`):

```powershell
git remote add upstream https://github.com/pretix/pretix
git remote set-url --push upstream DISABLED
git remote -v
```

## 6. Traer lo que no está en GitHub

Desde la otra PC, con un pendrive o una carpeta compartida, copiá:

| Qué | De dónde | A dónde |
|---|---|---|
| Carpeta `privado` (planos reales, copias de la base, plan de negocios, documentación en Word) | `D:\Ticketing\AndinaTickets\privado` | La misma ruta |
| Notas de Claude (opcional) | `C:\Users\<usuario>\.claude\projects\D--Ticketing-AndinaTickets` | La misma ruta |

La copia de la base tiene datos de compradores y la clave secreta del sistema: no la subas
a GitHub ni la mandes por mail.

### Hacer la copia de los datos en la PC vieja

Con Docker funcionando en la PC vieja, en `D:\Ticketing\AndinaTickets`:

```powershell
mkdir privado\migracion -Force
docker exec andina-tickets-db-1 pg_dump -U andina -d andina_tickets -Fc -f /tmp/andina_tickets.dump
docker cp andina-tickets-db-1:/tmp/andina_tickets.dump privado\migracion\andina_tickets.dump
docker exec andina-tickets-web-1 tar czf /tmp/datos.tar.gz -C /data .secret media
docker cp andina-tickets-web-1:/tmp/datos.tar.gz privado\migracion\datos.tar.gz
```

- `andina_tickets.dump`: la base de datos completa (eventos, pedidos, salas, usuarios,
  configuración).
- `datos.tar.gz`: la clave secreta de pretix (`.secret`) y los archivos subidos (`media`).

## 7. Armar y arrancar el sistema

En la PC nueva, en `D:\Ticketing\AndinaTickets`. La primera vez tarda entre 10 y 20 minutos.

```powershell
docker compose -f deployment/docker/docker-compose.dev.yml build
docker compose -f deployment/docker/docker-compose.dev.yml up -d db
```

### Restaurar los datos (si los trajiste)

Con la base recién creada y todavía vacía:

```powershell
docker cp privado\migracion\andina_tickets.dump andina-tickets-db-1:/tmp/andina_tickets.dump
docker exec andina-tickets-db-1 pg_restore -U andina -d andina_tickets --no-owner /tmp/andina_tickets.dump
```

Ahora arrancá todo y poné la clave secreta y los archivos:

```powershell
docker compose -f deployment/docker/docker-compose.dev.yml up -d
docker cp privado\migracion\datos.tar.gz andina-tickets-web-1:/tmp/datos.tar.gz
docker exec andina-tickets-web-1 tar xzf /tmp/datos.tar.gz -C /data
docker compose -f deployment/docker/docker-compose.dev.yml restart web
```

Si no trajiste datos, alcanza con `up -d`. Después creá el primer usuario administrador con
`docker exec -it andina-tickets-web-1 python3 /pretix/src/manage.py createsuperuser`, ya que
la base arranca vacía.

## 8. Comprobar que anda

- Panel: http://localhost:8130/control/ (con los datos restaurados, entrás con el mismo
  usuario de siempre).
- Correos de prueba: http://localhost:8026 (Mailpit).
- Pruebas automáticas (tienen que pasar todas):

```powershell
docker exec -e PRETIX_DATABASE_BACKEND=sqlite3 -e PRETIX_DATABASE_NAME= andina-tickets-web-1 sh -c 'cd /pretix/src && python3 -m pytest --ds=tests.settings tests/plugins/andinamercadopago tests/plugins/andinaseating -p no:cacheprovider'
```

Si en el panel aparece el aviso de la licencia, falta la configuración de la licencia: sin
datos restaurados hay que completarla (valores en `ANDINA.md`, "Verificación de la licencia").

## 9. Uso diario

| Para | Comando |
|---|---|
| Ver si está corriendo | `docker compose -f deployment/docker/docker-compose.dev.yml ps` |
| Ver qué dice el sistema (errores) | `docker compose -f deployment/docker/docker-compose.dev.yml logs -f web` (salir con Ctrl+C) |
| Apagarlo | `docker compose -f deployment/docker/docker-compose.dev.yml stop` |
| Prenderlo | `docker compose -f deployment/docker/docker-compose.dev.yml up -d` |
| Rearmarlo después de traer cambios de pretix | `docker compose -f deployment/docker/docker-compose.dev.yml up -d --build` |

Nunca uses `down -v`: la `-v` borra los volúmenes, o sea la base de datos.

## 10. Trabajar desde otra computadora (escritorio remoto)

En la PC que hace de servidor:

- **Que no se duerma:** Configuración → Sistema → Inicio/apagado y batería (o "Energía") →
  suspender: **Nunca**, enchufada.
- **Escritorio remoto de Windows:** Configuración → Sistema → Escritorio remoto → Activado.
  Solo existe en Windows **Pro**. En Windows **Home** usá otra herramienta, como AnyDesk,
  RustDesk o Escritorio remoto de Chrome.
- Anotá el nombre de la PC (Configuración → Sistema → Información) para conectarte desde la
  notebook: Inicio → "Conexión a Escritorio remoto" → ese nombre.

Trabajando por escritorio remoto todo pasa en la PC servidor: las direcciones `localhost`
de esta guía siguen funcionando igual.

## 11. La PC vieja

Cuando la nueva funcione, apagá el sistema en la vieja para no tener dos copias que se
separan:

```powershell
docker compose -f deployment/docker/docker-compose.dev.yml stop
```

Los datos quedan guardados ahí, por las dudas.

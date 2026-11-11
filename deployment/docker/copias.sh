#!/bin/sh
# AndinaTickets: copias de producción, una por día (contenedor "copias" de docker-compose.produccion.yml).
# - La base: pg_dump comprimido.
# - Los archivos de pretix (/data: imágenes de los eventos, facturas, archivos subidos, la clave interna si no
#   está en .env.produccion), sin los registros ni los archivos que pretix vuelve a generar solo.
# Se guardan las últimas COPIAS_DIAS (14 si no se dice otra cosa). Estas copias quedan en el mismo servidor: hay
# que bajarlas también a otro lado (ver INSTALAR.md, "Producción").
set -u
DIAS="${COPIAS_DIAS:-14}"
export PGPASSWORD="${POSTGRES_PASSWORD}"

until pg_isready -h db -U "${POSTGRES_USER}" -q; do
	echo "copias: esperando la base..."
	sleep 5
done

while true; do
	fecha=$(date +%Y-%m-%d_%H%M)
	if pg_dump -h db -U "${POSTGRES_USER}" "${POSTGRES_DB}" | gzip > "/copias/base-${fecha}.sql.gz.tmp"; then
		mv "/copias/base-${fecha}.sql.gz.tmp" "/copias/base-${fecha}.sql.gz"
		echo "copias: base-${fecha}.sql.gz"
	else
		rm -f "/copias/base-${fecha}.sql.gz.tmp"
		echo "copias: FALLÓ la copia de la base" >&2
	fi
	if tar -czf "/copias/archivos-${fecha}.tar.gz.tmp" -C / \
			--exclude=data/logs --exclude=data/media/cachedfiles --exclude=data/cache data; then
		mv "/copias/archivos-${fecha}.tar.gz.tmp" "/copias/archivos-${fecha}.tar.gz"
		echo "copias: archivos-${fecha}.tar.gz"
	else
		rm -f "/copias/archivos-${fecha}.tar.gz.tmp"
		echo "copias: FALLÓ la copia de los archivos" >&2
	fi
	find /copias -name '*.gz' -mtime +"${DIAS}" -delete
	sleep 86400
done

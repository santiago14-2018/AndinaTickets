# Carpeta privado

Todo lo que se guarde acá **nunca se sube a Git**: está excluido en `.gitignore`.
La única excepción es este archivo.

Va acá lo que no puede ser público:

- planos reales de las salas (CSV o JSON);
- copias de la base de datos;
- configuración del servidor de producción;
- contratos, precios y comisiones de cada productor.

Las credenciales de Mercado Pago **no** van acá. Se cargan en el panel, en *Parametrizaciones
globales → Ajustes*, y quedan guardadas en la base de datos.

Hay que hacer copia de seguridad de esta carpeta por otro medio, porque GitHub no la tiene.

# Carpeta privado

Todo lo que se guarde acá **nunca se sube a Git**: está excluido en `.gitignore`.
La única excepción es este archivo.

Va acá lo que no puede ser público:

- planos reales de las salas (CSV o JSON);
- copias de la base de datos;
- configuración del servidor de producción;
- contratos, precios y comisiones de cada productor;
- plan de negocios (`PlanDeNegocios.md`);
- documentación interna en Word (`documentacion/`: manual de usuario y guía técnica; las
  versiones viejas en `documentacion/anteriores/`). Tiene que abrir en Word 2007.

Las credenciales de Mercado Pago **no** van acá. Se cargan en el panel, en *Parametrizaciones
globales → Ajustes*, y quedan guardadas en la base de datos.

Este repositorio no la tiene: se respalda en el repositorio privado `AndinaTickets-Privado`
(`D:\Ticketing\AndinaTickets-Privado`), con su `respaldar.ps1`. Ver el LEEME.md de ese repositorio.

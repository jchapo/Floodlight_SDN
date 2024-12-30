Implementación de una Arquitectura SDN en la PUCP
Este proyecto presenta una solución basada en redes definidas por software (SDN) para mejorar la seguridad, disponibilidad y escalabilidad de la red de campus de la Pontificia Universidad Católica del Perú (PUCP).

Descripción del Proyecto
La red implementa un controlador SDN Floodlight que gestiona switches OpenFlow, permitiendo la creación y aplicación de reglas dinámicas y estáticas para:

Controlar el acceso a la red mediante autenticación 802.1X (portal cautivo con Flask y FreeRADIUS).
Restringir el acceso a recursos privilegiados según el rol del usuario.
Detectar y mitigar ataques de tipo DDoS y fuerza bruta en la intranet.
Arquitectura
La topología incluye:

Controlador SDN Floodlight: Gestor centralizado de políticas de flujo y tráfico.
Switches OpenFlow: Manejan el tráfico interno de la red bajo las reglas definidas por el controlador.
FreeRADIUS + MySQL: Autenticación centralizada y base de datos para gestionar usuarios y roles.
Portal Cautivo Flask: Interfaz para la autenticación de usuarios.
Gateway: Punto de conexión hacia internet y servicios externos.
Características Destacadas
Segmentación de Red: Uso de VLANs y reglas de enrutamiento basadas en roles para separar grupos de usuarios (estudiantes, docentes, administrativos).
Mitigación de Ataques: Implementación de límites de sesiones, bloqueo de intentos fallidos y reglas dinámicas contra ataques DDoS.
Escalabilidad y Rendimiento: Soporte para hasta 1,000 dispositivos simultáneos y optimización del tráfico crítico con políticas QoS.
Pasos Clave en la Configuración
Eliminación de módulos dinámicos en Floodlight para controlar manualmente las reglas de flujo.
Integración de FreeRADIUS con SQL para la validación de credenciales y asignación de políticas.
Desarrollo del Portal Cautivo con Flask, conectado al controlador para aplicar reglas específicas por usuario.
Este proyecto combina tecnologías modernas como OpenFlow, Flask, y Floodlight para ofrecer una red académica robusta, segura y adaptable.

import sys
import re
import yaml
import threading
import os
import requests
from clases import StaticFlowPusher, Curso, Alumno, Servidor, Servicio
from flask import Flask, request, jsonify
import logging
import time

# Listas globales para almacenar los objetos
alumnos = []
cursos = []
servidores = []  

# Diccionario para almacenar los flujos activos y sus marcas de tiempo
active_flows = {}

# Tiempo de inactividad en segundos (ej. 10 minutos)
INACTIVITY_TIMEOUT = 20  # 20 segundos

# DEFINE VARIABLES
controller_ip = '10.20.12.136' 
host_ip= '10.0.0.1'
portal_ip = '10.0.0.2'
freeradius_ip = '10.0.0.3'
target_api_devices = 'wm/device/'  # API para listar los dispositivos detectados
headers = {'Content-type': 'application/json', 'Accept': 'application/json'}
url_devices = f'http://{controller_ip}:8080/{target_api_devices}'

# Crear aplicación Flask
app = Flask(__name__)
# Desactivar los logs de Flask para mantener la consola limpia
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# Puerto fijo para el servidor
SERVER_PORT = 8083

# Variable global para indicar si el servidor debe seguir activo
server_running = False

def record_flow(username, client_ip, flow_data):
    """ Registra un flujo con su marca de tiempo """
    timestamp = time.time()  # Obtiene el tiempo actual
    flow_key = f"{username}_{client_ip}"
    
    if flow_key not in active_flows:
        active_flows[flow_key] = []
    
    # Almacena el flujo junto con su marca de tiempo
    active_flows[flow_key].append({
        "flow_data": flow_data,
        "timestamp": timestamp
    })

def cleanup_inactive_flows():
    """ Elimina los flujos que han estado inactivos más allá del tiempo configurado """
    current_time = time.time()
    for flow_key, flows in list(active_flows.items()):
        active_flows[flow_key] = [
            flow for flow in flows if current_time - flow['timestamp'] <= INACTIVITY_TIMEOUT
        ]
        
        if not active_flows[flow_key]:
            print(f"Eliminando flujos inactivos para el cliente {flow_key} (sin actividad por más de {INACTIVITY_TIMEOUT} segundos)")
            del active_flows[flow_key]  # Si no quedan flujos activos, elimina la clave

def periodic_cleanup():
    """ Ejecutar la limpieza de flujos inactivos cada cierto tiempo. """
    while True:
        time.sleep(INACTIVITY_TIMEOUT)  # Esperar por el tiempo de inactividad
        cleanup_inactive_flows()

# Iniciar el proceso de limpieza periódica en un hilo separado
cleanup_thread = threading.Thread(target=periodic_cleanup)
cleanup_thread.daemon = True  # Asegurarse de que el hilo se cierre cuando termine el programa principal
cleanup_thread.start()

# Ruta para configurar flujos
@app.route('/configure_flows', methods=['POST'])
def configure_flows():
    try:
        # Obtener los datos recibidos desde H2
        data = request.json
        username = data['username']
        client_ip = data['client_ip']
        courses = data['courses']
        
        # Mostrar los datos recibidos
        print("\n=== Datos recibidos desde H2 ===")
        print(f"Usuario: {username}")
        print(f"IP del cliente: {client_ip}")
        print("Cursos:")
        for course in courses:
            print(f"  - IP Servidor: {course[0]}, Puerto: {course[1]}, Servicio: {course[2]}, Curso: {course[3]}")
        
        # Configurar los flujos para cada curso
        for course in courses:
            servidor_ip, puerto, servicio, nombre_curso = course
            
            # Obtener puntos de conexión entre cliente y servidor
            resultado = obtener_puntos_conexion_ip(client_ip, servidor_ip)
            if resultado is None:
                print(f"Error: No se encontraron puntos de conexión entre {client_ip} y {servidor_ip}")
                continue
            
            mac_servidor, dpid_servidor, puerto_servidor, mac_cliente, dpid_cliente, puerto_cliente = resultado
            
            # Obtener ruta entre cliente y servidor
            ruta = get_route(dpid_cliente, puerto_cliente, dpid_servidor, puerto_servidor)
            if isinstance(ruta, str):
                print(f"Error al obtener la ruta: {ruta}")
                continue
            
            # Imprimir detalles del flujo que se va a configurar
            print(f"\nConfigurando flujos para el servicio {servicio} en el curso {nombre_curso}:")
            print(f"  - IP Servidor: {servidor_ip}, Puerto: {puerto}")
            
            # Configurar reglas en los switches
            pusher = StaticFlowPusher(controller_ip)
            for switch, puerto_entrada, puerto_salida in ruta:
                print(f"pueto_entrada {puerto_entrada}:")
                print(f"pueto_salida {puerto_salida}:")
                # Crear reglas TCP
                flujo_tcp_cliente_a_servidor = {
                    "switch": switch,
                    "name": f"flow_{switch}_{username}_{servicio}_to_server",
                    "cookie": "0",
                    "priority": "32768",
                    "actions": f"output={puerto_entrada}",
                    "match": {
                        "eth_type": "0x0800",
                        "ipv4_src": client_ip,
                        "ipv4_dst": servidor_ip,
                        "ip_proto": "0x06",
                        "tcp_dst": str(puerto)
                    }
                }
                flujo_tcp_servidor_a_cliente = {
                    "switch": switch,
                    "name": f"flow_{switch}_{username}_{servicio}_from_server",
                    "cookie": "0",
                    "priority": "32768",
                    "actions": f"output={puerto_salida}",
                    "match": {
                        "eth_type": "0x0800",
                        "ipv4_src": servidor_ip,
                        "ipv4_dst": client_ip,
                        "ip_proto": "0x06",
                        "tcp_src": str(puerto)
                    }
                }
                # Insertar las reglas
                pusher.set(flujo_tcp_cliente_a_servidor)
                pusher.set(flujo_tcp_servidor_a_cliente)
                print(f"  - Flujo configurado para switch {switch}:")
                print(f"    - Flujo Cliente a Servidor: {flujo_tcp_cliente_a_servidor['name']}")
                print(f"    - Flujo Servidor a Cliente: {flujo_tcp_servidor_a_cliente['name']}")

                # Registrar el flujo con su timestamp
                record_flow(username, client_ip, flujo_tcp_cliente_a_servidor)
                record_flow(username, client_ip, flujo_tcp_servidor_a_cliente)
        
        return jsonify({"message": "Flujos configurados exitosamente"}), 200

    except Exception as e:
        print(f"Error en configure_flows: {e}")
        return jsonify({"error": str(e)}), 500


# Función para mostrar el menú principal
def mostrar_menu_principal():
    while True:
        print("="*80)
        print("  MENÚ PRINCIPAL")
        print("="*80)
        #print("1. 📂 Importar YAML")
        #print("2. 💾 Exportar YAML")
        #print("3. 📚 Cursos")
        #print("4. 👥 Alumnos")
        #print("5. 🖥️  Servidores y servicios")
        print("1. 🔌 Conexiones")
        print("2. 🚀 Arrancar servidor H2")
        print("0. 🚪 Salir")
        print("="*80)
        
        opcion = input("Selecciona una opción: ").strip()
        
        if opcion == "6":
            importar_datos_yaml()
        elif opcion == "7":
            exportar_datos_yaml()
        elif opcion == "3":
            menu_gestion_cursos()
        elif opcion == "4":
            menu_gestion_alumnos()
        elif opcion == "5":
            menu_gestion_servidores()
        elif opcion == "1":
            menu_gestion_conexiones()
        elif opcion == "2":
            arrancar_servidor()
        elif opcion == "0":
            print("Saliendo...")
            sys.exit(0)  # Salir del programa
        else:
            print("Opción no válida. Intenta de nuevo.")

# Función para importar datos desde un archivo YAML
def importar_datos_yaml():
    try:
        # Solicitar al usuario que ingrese el nombre del archivo o ruta
        nombre_archivo = input("Ingrese el nombre o la ruta del archivo YAML para importar: ")

        # Verificar si el archivo existe
        if not os.path.isfile(nombre_archivo):
            print(f"El archivo {nombre_archivo} no existe.")
            return

        # Abrir el archivo YAML
        with open(nombre_archivo, "r") as file:
            data = yaml.safe_load(file)

        # Limpiar las listas para nuevos datos
        alumnos.clear()
        cursos.clear()
        servidores.clear()

        # Procesar los datos de los alumnos
        for alumno_data in data.get("alumnos", []):
            alumno = Alumno(
                nombre=alumno_data["nombre"],
                codigo=alumno_data["codigo"],
                mac=alumno_data["mac"]
            )
            alumnos.append(alumno)  # Añadimos el alumno a la lista global

        # Procesar los datos de los servidores
        for servidor_data in data.get("servidores", []):
            servidor = Servidor(
                nombre=servidor_data["nombre"],
                ip=servidor_data["ip"]
            )
            # Agregar servicios al servidor
            for servicio_data in servidor_data["servicios"]:
                servicio = Servicio(
                    nombre=servicio_data["nombre"],
                    protocolo=servicio_data["protocolo"],
                    puerto=servicio_data["puerto"]
                )
                servidor.agregar_servicio(servicio)
            servidores.append(servidor)  # Añadimos el servidor a la lista

        # Procesar los datos de los cursos
        for curso_data in data.get("cursos", []):
            curso = Curso(
                codigo=curso_data["codigo"],
                estado=curso_data["estado"],
                nombre=curso_data["nombre"]
            )

            # Agregar los alumnos al curso
            for codigo_alumno in curso_data.get("alumnos", []):
                alumno = next((al for al in alumnos if al.codigo == codigo_alumno), None)
                if alumno:
                    curso.agregar_alumno(alumno)

            # Agregar los servidores al curso y también agregar los servicios permitidos
            for servidor_data in curso_data.get("servidores", []):
                servidor = next((ser for ser in servidores if ser.nombre == servidor_data["nombre"]), None)
                if servidor:
                    curso.agregar_servidor(servidor)

                    # Agregar los servicios permitidos de ese servidor en el curso
                    for servicio_permitido in servidor_data.get("servicios_permitidos", []):
                        # Buscar el servicio correspondiente
                        servicio = next(
                            (serv for serv in servidor.servicios if serv.nombre.lower() == servicio_permitido.lower()), 
                            None
                        )
                        if servicio:
                            curso.agregar_servicio_permitido(servicio)

            cursos.append(curso)

        print("Datos importados exitosamente.")
    except Exception as e:
        print(f"Error al importar los datos: {e}")


# Función para exportar datos a un archivo YAML
def exportar_datos_yaml():
    try:
        # Preguntar al usuario por el nombre del archivo donde se guardarán los datos
        nombre_archivo = input("Ingrese el nombre del archivo YAML para exportar: ")

        # Preparar los datos para exportar
        data = {
            "alumnos": [{"nombre": alumno.nombre, "codigo": alumno.codigo, "mac": alumno.mac} for alumno in alumnos],
            "cursos": [{
                "codigo": curso.codigo,
                "estado": curso.estado,
                "nombre": curso.nombre,
                "alumnos": [alumno.codigo for alumno in curso.alumnos],
                "servidores": [{"nombre": servidor.nombre} for servidor in curso.servidores]
            } for curso in cursos],
            "servidores": [{
                "nombre": servidor.nombre,
                "ip": servidor.ip,
                "servicios": [{
                    "nombre": servicio.nombre,
                    "protocolo": servicio.protocolo,
                    "puerto": servicio.puerto
                } for servicio in servidor.servicios]
            } for servidor in servidores]  # Exportando directamente desde la lista de servidores
        }

        # Guardar los datos en el archivo YAML
        with open(nombre_archivo, "w") as file:
            yaml.dump(data, file, default_flow_style=False, allow_unicode=True)

        print(f"Datos exportados exitosamente a {nombre_archivo}.")
    except Exception as e:
        print(f"Error al exportar los datos: {e}")

# Función para gestionar Cursos
def menu_gestion_cursos():
    while True:
        print("="*80)
        print("📚 Gestión de Cursos")
        print("="*80)
        print("1. Listar Todos los Cursos")
        print("2. Listar Cursos por Servidor")
        print("3. Listar Cursos por Servicio")
        print("4. Detalle Curso")
        print("5. Actualizar Curso")
        print("0. Volver al Menú Principal")
        print("="*80)
        opcion = input("Selecciona una opción: ").strip()
        
        if opcion == "1":
            listar_cursos()
        elif opcion == "2":
            listar_cursos_por_servidor()
        elif opcion == "3":
            listar_cursos_por_servicio()
        elif opcion == "4":
            detalles_curso()
        elif opcion == "5":
            actualizar_curso()
        elif opcion == "0":
            break
        else:
            print("Opción no válida. Intenta de nuevo.")

# Función para mostrar todos los cursos
def listar_cursos():
    print("\nListado de Cursos:")
    if cursos:
        for curso in cursos:
            print(f"Código: {curso.codigo}, Nombre: {curso.nombre}, Estado: {curso.estado}")
    else:
        print("No hay cursos disponibles.")

# Función para listar cursos que tienen un servidor registrado
def listar_cursos_por_servidor():
    print("="*80)
    print("📚 Listar Cursos por Servidor")
    print("="*80)

    # Solicitar al usuario el nombre del servidor
    nombre_servidor = input("Ingresa el nombre del servidor: ").strip().upper()

    # Buscar los cursos que tienen ese servidor registrado
    cursos_con_servidor = [curso for curso in cursos if any(servidor.nombre.upper() == nombre_servidor for servidor in curso.servidores)]
    
    if cursos_con_servidor:
        print(f"\nCursos que tienen el servidor '{nombre_servidor}' registrado:")
        for curso in cursos_con_servidor:
            print(f"- {curso.nombre} (Código: {curso.codigo})")
    else:
        print(f"No se encontraron cursos con el servidor '{nombre_servidor}' registrado.")

# Función para listar cursos que tienen un servicio registrado
def listar_cursos_por_servicio():
    print("="*80)
    print("📚 Listar Cursos por Servicio")
    print("="*80)

    # Solicitar al usuario el nombre del servicio
    nombre_servicio = input("Ingresa el nombre del servicio: ").strip().upper()

    # Buscar los cursos que tienen ese servicio permitido en sus servidores
    cursos_con_servicio = [curso for curso in cursos if any(servicio.nombre.upper() == nombre_servicio for servicio in curso.servicios_permitidos)]

    if cursos_con_servicio:
        print(f"\nCursos que tienen el servicio '{nombre_servicio}' permitido:")
        for curso in cursos_con_servicio:
            print(f"- {curso.nombre} (Código: {curso.codigo})")
    else:
        print(f"No se encontraron cursos con el servicio '{nombre_servicio}' permitido.")


# Función para mostar detalle de curso
def detalles_curso():
    # Solicitar al usuario el código del curso
    codigo_curso = input("Ingresa el código del curso: ").strip().upper()  # Convertir a mayúsculas
    
    # Buscar el curso por código
    curso_encontrado = next((curso for curso in cursos if curso.codigo == codigo_curso), None)
    
    # Verificar si el curso fue encontrado
    if curso_encontrado:
        # Mostrar los detalles del curso
        print(f"Código: {curso_encontrado.codigo}")
        print(f"Nombre: {curso_encontrado.nombre}")
        print(f"Estado: {curso_encontrado.estado}")
        
        # Listar los alumnos registrados en el curso
        if curso_encontrado.alumnos:
            print("Alumnos registrados:")
            for alumno in curso_encontrado.alumnos:
                print(f"  - {alumno.nombre}")
        else:
            print("No hay alumnos registrados en este curso.")
    else:
        print(f"No se encontró ningún curso con el código '{codigo_curso}'.")

# Función para actualizar curso
def actualizar_curso():
    # Solicitar el código del curso a actualizar
    codigo_curso = input("Ingresa el código del curso a actualizar: ").strip().upper()
    
    # Buscar el curso en la lista
    curso_encontrado = next((curso for curso in cursos if curso.codigo == codigo_curso), None)
    
    if curso_encontrado:
        while True:
            # Mostrar menú de opciones
            print(f"\nCurso encontrado: {curso_encontrado.nombre}")
            print("1. Agregar alumno al curso")
            print("2. Eliminar alumno del curso")
            print("3. Cancelar y regresar al menú de gestión de cursos")
            opcion = input("Selecciona una opción: ").strip()
            
            if opcion == "1":
                # Listar alumnos que no están en el curso
                alumnos_no_inscritos = [alumno for alumno in alumnos if alumno not in curso_encontrado.alumnos]
                if alumnos_no_inscritos:
                    print("\nAlumnos disponibles para agregar:")
                    for idx, alumno in enumerate(alumnos_no_inscritos, start=1):
                        print(f"{idx}. {alumno.nombre} (MAC: {alumno.mac})")
                    print("0. Cancelar y regresar al menú de gestión de cursos")
                    
                    try:
                        # Seleccionar el número de alumno
                        seleccion = int(input("Ingresa el número del alumno que deseas agregar: "))
                        if seleccion == 0:
                            print("Operación cancelada. Regresando al menú de gestión de cursos.")
                            return
                        elif 1 <= seleccion <= len(alumnos_no_inscritos):
                            alumno_seleccionado = alumnos_no_inscritos[seleccion - 1]
                            curso_encontrado.agregar_alumno(alumno_seleccionado)
                            print(f"\nEl alumno {alumno_seleccionado.nombre} ha sido agregado al curso {curso_encontrado.nombre}.")
                        else:
                            print("Número fuera de rango. Intenta de nuevo.")
                    except ValueError:
                        print("Entrada no válida. Intenta de nuevo.")
                else:
                    print("No hay alumnos disponibles para agregar.")
            
            elif opcion == "2":
                # Listar alumnos del curso
                if curso_encontrado.alumnos:
                    print("\nAlumnos inscritos en el curso:")
                    for idx, alumno in enumerate(curso_encontrado.alumnos, start=1):
                        print(f"{idx}. {alumno.nombre}")
                    print("0. Cancelar")
                    
                    try:
                        # Seleccionar el número de alumno a eliminar
                        seleccion = int(input("Ingresa el número del alumno que deseas eliminar: "))
                        if seleccion == 0:
                            print("Operación cancelada.")
                            return
                        elif 1 <= seleccion <= len(curso_encontrado.alumnos):
                            alumno_seleccionado = curso_encontrado.alumnos[seleccion - 1]
                            curso_encontrado.alumnos.remove(alumno_seleccionado)
                            print(f"\nEl alumno {alumno_seleccionado.nombre} ha sido removido del curso {curso_encontrado.nombre}.")
                        else:
                            print("Número fuera de rango. Intenta de nuevo.")
                    except ValueError:
                        print("Entrada no válida. Intenta de nuevo.")
                else:
                    print("No hay alumnos inscritos en este curso.")
            
            elif opcion == "3":
                print("Regresando al menú de gestión de cursos.")
                return
            
            else:
                print("Opción no válida. Intenta de nuevo.")
    else:
        print(f"No se encontró un curso con el código '{codigo_curso}'.")

# Función para gestionar Alumnos
def menu_gestion_alumnos():
    while True:
        print("="*80)
        print("👥 Gestión de Alumnos")
        print("="*80)
        print("1. Listar todos los Alumnos")
        print("2. Listar Alumnos de un Curso")
        print("3. Detalle Alumno")
        print("4. Añadir Alumno")
        print("0. Volver al Menú Principal")
        print("="*80)
        opcion = input("Selecciona una opción: ").strip()
        
        if opcion == "1":
            listar_alumnos()
        elif opcion == "2":
            listar_alumnos_por_curso()         
        elif opcion == "3":
            detalles_alumno()
        elif opcion == "4":
            añadir_alumno()  
        elif opcion == "0":
            break
        else:
            print("Opción no válida. Intenta de nuevo.")

# Función para listar todos los alumnos
def listar_alumnos():
    print("\nListado de Alumnos:")
    for alumno in alumnos:
        print(f"Código: {alumno.codigo}, Nombre: {alumno.nombre}, MAC: {alumno.mac}")

# Función para listar los alumnos de un curso específico
def listar_alumnos_por_curso():
    print("Listar Alumnos de un Curso")
    # Solicitar el código del curso
    codigo_curso = input("Ingresa el código del curso: ").strip()
    
    # Buscar el curso por código
    curso_encontrado = next((curso for curso in cursos if str(curso.codigo) == codigo_curso), None)
    
    if curso_encontrado:
        if curso_encontrado.estado == "DICTANDO":
            print(f"\nListado de Alumnos en el curso '{curso_encontrado.nombre}' (Código: {codigo_curso}):")
            
            for codigo_alumno in curso_encontrado.alumnos:
                print(f"Código: {codigo_alumno.codigo}, Nombre: {codigo_alumno.nombre}, MAC: {codigo_alumno.mac}")
        else:
            print(f"El curso '{curso_encontrado.nombre}' no está en estado 'DICTANDO'.")
    else:
        print(f"No se encontró ningún curso con el código '{codigo_curso}'.")

# Función para mostar detalle de alumno
def detalles_alumno():
    # Solicitar al usuario el código del alumno
    codigo_alumno = input("Ingresa el código del alumno: ").strip()
    
    # Verificar si el código es válido
    if not codigo_alumno:
        print("El código del alumno no puede estar vacío. Intenta de nuevo.")
        return
    
    # Normalizar la búsqueda para evitar inconsistencias
    alumno_encontrado = next((alumno for alumno in alumnos if str(alumno.codigo).strip() == codigo_alumno), None)
    
    # Verificar si el alumno fue encontrado
    if alumno_encontrado:
        # Mostrar los detalles del alumno
        print(f"Código: {alumno_encontrado.codigo}")
        print(f"Nombre: {alumno_encontrado.nombre}")
        print(f"MAC: {alumno_encontrado.mac}")
    else:
        print(f"\nNo se encontró ningún alumno con el código '{codigo_alumno}'. Verifica la información e intenta de nuevo.")

# Función para añadir un Alumno
def añadir_alumno():
    nombre_alumno = input("Ingresa el nombre del alumno: ")
    codigo_alumno = input("Ingresa el código del alumno: ")
    while True:
        mac = input("Ingresa la dirección MAC del PC: ")
        if es_mac_valida(mac):
            break
        else:
            print("La dirección MAC no es válida. Intenta de nuevo.")
    
    alumno = Alumno(nombre_alumno, codigo_alumno, mac)
    alumnos.append(alumno)  # Añadir el alumno a la lista
    print(f"Alumno añadido exitosamente.")

# Función para gestionar Servidores
def menu_gestion_servidores():
    while True:
        print("="*80)
        print("💻 Gestión de Servidores")
        print("="*80)
        print("1. Listar Servidores")
        print("2. Detalle Servidor")
        print("0. Volver al Menú Principal")
        print("="*80)
        opcion = input("Selecciona una opción: ").strip()
        
        if opcion == "1":
            listar_servidores()
        elif opcion == "2":
            detalles_servidor()
        elif opcion == "0":
            break
        else:
            print("Opción no válida. Intenta de nuevo.")

# Función para listar servidores
def listar_servidores():
    print("\nListado de Servidores:")
    for servidor in servidores:
        print(f"Nombre: {servidor.nombre}, IP: {servidor.ip}")

# Función para ver detalles de un servidor
def detalles_servidor():
    # Solicitar al usuario el nombre del servidor
    nombre_servidor = input("Ingresa el nombre del servidor: ").strip()
    
    # Buscar el servidor por nombre
    servidor_encontrado = next((servidor for servidor in servidores if servidor.nombre.lower() == nombre_servidor.lower()), None)
    
    # Verificar si el servidor fue encontrado
    if servidor_encontrado:
        # Mostrar los detalles del servidor
        print(f"\nDetalles del Servidor:")
        print(f"Nombre: {servidor_encontrado.nombre}")
        print(f"IP: {servidor_encontrado.ip}")
        print(f"Servicios: {[servicio.nombre for servicio in servidor_encontrado.servicios]}")
    else:
        print(f"No se encontró ningún servidor con el nombre '{nombre_servidor}'.")

# Función para gestionar Conexiones
def menu_gestion_conexiones():
    while True:
        print("="*80)
        print("🔌 Gestión de Conexiones")
        print("="*80)
        #print("5. Crear Conexión")
        #print("6. Listar Conexiones")
        #print("3. Borrar Conexión")
        #print("4. Establecer conexion")
        print("1. Habilitar Portal")
        print("2. Tráfico FreeRadius-MySQL")
        print("0. Volver al Menú Principal")
        print("="*80)
        
        opcion = input("Selecciona una opción: ").strip()
        
        if opcion == "5":
            crear_conexion()
        elif opcion == "6":
            listar_conexiones()
        elif opcion == "3":
            borrar_conexion()
        elif opcion == "4":
            establecer_conexion()
        elif opcion == "1":
            redireccion_portal_cautivo()
        elif opcion == "2":
            trafico_a_freeradius()    
        elif opcion == "0":
            break
        else:
            print("Opción no válida. Intenta de nuevo.")

# Función para obtener la ruta entre dos puntos
def get_route(dpid_origen, puerto_origen, dpid_destino, puerto_destino):
    route_url = f'http://{controller_ip}:8080/wm/topology/route/{dpid_origen}/{puerto_origen}/{dpid_destino}/{puerto_destino}/json'
    response = requests.get(route_url, headers=headers)
    
    if response.status_code == 200:
        data = response.json()
        
        if data:
            ruta = []
            # Iterar sobre la respuesta para crear la ruta con puertos de entrada y salida
            for i in range(0, len(data), 2):  # Iterar de dos en dos
                switch_entrada = data[i]['switch']  # Switch de entrada
                puerto_entrada = data[i]['port']['portNumber']  # Puerto de entrada
                switch_salida = data[i+1]['switch']  # Switch de salida (el siguiente en la lista)
                puerto_salida = data[i+1]['port']['portNumber']  # Puerto de salida (el siguiente en la lista)
                
                # Añadir el par (switch, puerto_entrada, puerto_salida) a la ruta
                ruta.append((switch_entrada, puerto_entrada, puerto_salida))
            
            return ruta
        else:
            return "No se encontró una ruta entre los dispositivos."
    else:
        return f"ERROR | Status Code: {response.status_code}"

def obtener_puntos_conexion(ip_servidor, mac_alumno):
    # Realizar la solicitud GET a la API de dispositivos
    response = requests.get(url=url_devices, headers=headers, timeout=10)
    
    if response.status_code == 200:
        data = response.json()
        mac_servidor = None
        dpid_servidor = None
        puerto_servidor = None
        dpid_alumno = None
        puerto_alumno = None
        ip_alumno = None
        
        for device in data:
            # Buscar la MAC del servidor
            if ip_servidor in device.get('ipv4', []):  # Verificar lista de IPv4
                for mac in device.get('mac', []):
                    mac_servidor = mac
                    for point in device.get('attachmentPoint', []):
                        dpid_servidor = point['switchDPID']
                        puerto_servidor = point['port']

            # Buscar la MAC del alumno
            if mac_alumno in device.get('mac', []):  # Verificar que la MAC esté presente
                ipv4_list = device.get('ipv4', [])
                if ipv4_list:  # Verificar si contiene datos
                    ip_alumno = ipv4_list[0]
                for point in device.get('attachmentPoint', []):
                    dpid_alumno = point['switchDPID']
                    puerto_alumno = point['port']
            
            if dpid_alumno and dpid_servidor:  # Verificar que ambos no estén vacíos
                return mac_servidor, dpid_servidor, puerto_servidor, dpid_alumno, puerto_alumno, ip_alumno
        
        return mac_servidor, dpid_servidor, puerto_servidor, dpid_alumno, puerto_alumno, ip_alumno
    else:
        print(f'FAILED REQUEST | STATUS: {response.status_code}')
        return None

def obtener_puntos_conexion_ip(ip_1, ip_2):
    # Realizar la solicitud GET a la API de dispositivos
    response = requests.get(url=url_devices, headers=headers, timeout=10)
    
    if response.status_code == 200:
        data = response.json()
        mac_1 = None
        dpid_1 = None
        puerto_1 = None
        mac_2 = None
        dpid_2 = None
        puerto_2 = None
        
        for device in data:
            # Buscar la MAC_1
            if ip_1 in device.get('ipv4', []):  # Verificar lista de IPv4
                for mac in device.get('mac', []):
                    mac_1 = mac
                    for point in device.get('attachmentPoint', []):
                        dpid_1 = point['switchDPID']
                        puerto_1 = point['port']

            # Buscar la MAC_1
            if ip_2 in device.get('ipv4', []):  # Verificar lista de IPv4
                for mac in device.get('mac', []):
                    mac_2 = mac
                    for point in device.get('attachmentPoint', []):
                        dpid_2 = point['switchDPID']
                        puerto_2 = point['port']
        
        return mac_1, dpid_1, puerto_1, mac_2, dpid_2, puerto_2
    else:
        print(f'FAILED REQUEST | STATUS: {response.status_code}')
        return None

# Lista de conexiones
conexiones = []

# Función para listar las conexiones
def listar_conexiones():
    if not conexiones:
        print("No hay conexiones registradas.")
    else:
        print("\nConexiones registradas:")
        for i, conexion in enumerate(conexiones, 1):
            print(f"{i}. Alumno: {conexion['alumno']}, Servidor: {conexion['servidor']}")

# Función para borrar una conexión
def borrar_conexion():
    listar_conexiones()
    if not conexiones:
        return  # Si no hay conexiones, sale de la función

    # Solicitar al usuario el número de conexión a borrar
    try:
        index = int(input("Ingresa el número de la conexión que deseas borrar: ")) - 1
        if 0 <= index < len(conexiones):
            conexion_eliminada = conexiones.pop(index)
            print(f"Conexión eliminada: Alumno {conexion_eliminada['alumno']}, Servidor {conexion_eliminada['servidor']}")
        else:
            print("Número de conexión inválido.")
    except ValueError:
        print("Entrada no válida. Debes ingresar un número.")

# Función para crear la conexión
def crear_conexion():
    # Solicitar el código del alumno
    codigo_alumno = input("Ingresa el código del alumno: ").strip()
    
    # Buscar al alumno en la lista de alumnos
    alumno_encontrado = next((alumno for alumno in alumnos if str(alumno.codigo).strip() == codigo_alumno), None)
    
    if not alumno_encontrado:
        print(f"No se encontró ningún alumno con el código '{codigo_alumno}'.")
        return

    # Mostrar el nombre del alumno encontrado
    print(f"Alumno encontrado: {alumno_encontrado.nombre}")
    
    # Solicitar el nombre del servidor
    nombre_servidor = input("Ingresa el nombre del servidor: ").strip()
    
    # Buscar el servidor
    servidor_encontrado = next((servidor for servidor in servidores if servidor.nombre == nombre_servidor), None)
    
    if not servidor_encontrado:
        print(f"No se encontró ningún servidor con el nombre '{nombre_servidor}'.")
        return
    
    # Añade la conexión a la lista después de seleccionar el servicio
    conexiones.append({
        'alumno': alumno_encontrado.nombre,
        'servidor': nombre_servidor,
    })
        
    # Buscar los cursos en los que el servidor está registrado
    cursos_encontrados = [
        curso for curso in cursos if any(srv.nombre == nombre_servidor for srv in curso.servidores)
    ]
    
    # Mostrar los cursos encontrados
    print(f"Cursos encontrados: {[curso.codigo for curso in cursos_encontrados]}")
    
    if not cursos_encontrados:
        print(f"El servidor '{nombre_servidor}' no está registrado en ningún curso.")
        return

    servicios_permitidos = set()

    # Verificar si el alumno pertenece a alguno de los cursos encontrados
    for curso in cursos_encontrados:
        if any(str(alumno.codigo) == codigo_alumno for alumno in curso.alumnos):  # Comparar con el código del alumno
            print(f"Conexión válida. El alumno '{alumno_encontrado.nombre}' pertenece al curso '{curso.nombre}'.")

            for servidor in curso.servidores:
                if servidor.nombre == nombre_servidor:
                    for servicio in servidor.servicios:
                        servicios_permitidos.add(servicio)

    # Solicitar al alumno seleccionar un servicio para la conexión
    if servicios_permitidos:
        nombres_servicios = [servicio.nombre for servicio in servicios_permitidos]
        servicio = input(f"Selecciona el servicio a usar ({', '.join(nombres_servicios)}): ").strip()
        for servicio_p in servicios_permitidos:
            if servicio_p.nombre == servicio:

                # Obtener protocolo y puerto del servicio
                protocolo = servicio_p.protocolo
                puerto = servicio_p.puerto
                
                # Obtener la IP del servidor y la MAC del alumno
                ip_servidor = servidor_encontrado.ip  # IP del servidor
                mac_alumno = alumno_encontrado.mac  # MAC del alumno
                
                # Obtener los puntos de conexión para ambos dispositivos
                resultados = obtener_puntos_conexion(ip_servidor, mac_alumno)
                
                if resultados:
                    mac_servidor, dpid_servidor, puerto_servidor, dpid_alumno, puerto_alumno, ip_alumno = resultados

                    if mac_servidor and dpid_servidor and puerto_servidor and dpid_alumno and puerto_alumno:
                        # Mostrar los puntos de conexión obtenidos
                        #print(f"Servidor: {nombre_servidor} (MAC: {mac_servidor}, DPID: {dpid_servidor}, Puerto: {puerto_servidor})")
                        #print(f"Alumno: {alumno_encontrado.nombre} (MAC: {mac_alumno}, DPID: {dpid_alumno}, Puerto: {puerto_alumno})")

                        # Obtener la ruta entre los puntos de conexión
                        ruta = get_route(dpid_alumno, puerto_alumno, dpid_servidor, puerto_servidor)
                        print(ruta)

                        if isinstance(ruta, list):
                            # Configurar los flujos en cada switch de la ruta
                            pusher = StaticFlowPusher(controller_ip)

                            # Iterar sobre la ruta, donde cada elemento ahora es (switch, puerto_entrada, puerto_salida)
                            for i, (switch, puerto_entrada, puerto_salida) in enumerate(ruta):
                                # Flujo de host a servidor
                                flujo_host_a_servidor = {
                                    "switch": switch,
                                    "name": f"flow_{switch}_h2s_{i}",
                                    "cookie": "0",  # Cookie es 0, podría ser un identificador único
                                    "priority": "32768",  # Prioridad
                                    "actions": f"output={puerto_salida}",  # La acción es enviar el paquete al puerto de salida
                                    "match": {
                                        "eth_type": "0x0800",  # Tipo de Ethernet (IPv4)
                                        "eth_src": mac_alumno,  # Dirección MAC del host
                                        "eth_dst": mac_servidor,  # Dirección MAC del servidor
                                        "ipv4_src": ip_alumno,  # Dirección IP de origen
                                        "ipv4_dst": ip_servidor,  # Dirección IP de destino
                                        "ip_proto": "0x06",  # TCP
                                        "tcp_dst": puerto_servidor  # Puerto de destino (puerto del servidor)
                                    }
                                }

                                #print(flujo_host_a_servidor)
                                pusher.set(flujo_host_a_servidor)

                                # Flujo de servidor a host
                                flujo_servidor_a_host = {
                                    "switch": switch,
                                    "name": f"flow_{switch}_s2h_{i}",
                                    "cookie": "0",  # Cookie es 0, podría ser un identificador único
                                    "priority": "32768",  # Prioridad
                                    "actions": f"output={puerto_entrada}",  # La acción es enviar el paquete al puerto de salida
                                    "match": {
                                        "eth_type": "0x0800",  # Tipo de Ethernet (IPv4)
                                        "eth_src": mac_servidor,  # Dirección MAC del servidor
                                        "eth_dst": mac_alumno,  # Dirección MAC del host
                                        "ipv4_src": ip_servidor,  # Dirección IP del servidor
                                        "ipv4_dst": ip_alumno,  # Dirección IP del host
                                        "ip_proto": "0x06",  # TCP
                                        "tcp_src": puerto_servidor  # Puerto de origen (puerto del servidor)
                                    }
                                }

                                #print(flujo_servidor_a_host)
                                pusher.set(flujo_servidor_a_host)
                                print(f"Flujos insertados con éxito en '{switch}'. Conexión establecida.")

                        else:
                            print(ruta)

                    else:
                        print("No se pudieron obtener las MACs, DPID o puertos de los dispositivos.")
                else:
                    print("Error al obtener la información de los puntos de conexión.")

            else:
                #print(f"El servicio '{servicio}' no es válido para este servidor en el curso '{curso.nombre}'.")
                return
        else:
            print(f"No hay servicios permitidos en el servidor '{nombre_servidor}' para el curso '{curso.nombre}'.")
            return

    # Si no se encontró una relación del alumno con los cursos del servidor
    print(f"El alumno '{alumno_encontrado.nombre}' no está registrado en los cursos asociados al servidor '{nombre_servidor}'.")

# Función para establecer la conexión entre el controlador y el servidor de authenticación
def redireccion_portal_cautivo():

    # Paso 1: Obtener los datos de conexión para los dispositivos
    resultado = obtener_puntos_conexion_ip(host_ip, portal_ip)
    if resultado is None:
        print("No se pudieron obtener los puntos de conexión.")
        return
    
    mac_1, dpid_1, puerto_1, mac_2, dpid_2, puerto_2 = resultado
    
    if not dpid_1 or not dpid_2:
        print("No se pudo determinar los puntos de conexión del H1 y H2.")
        return
    
    # Paso 2: Obtener la ruta entre el controlador y H3
    ruta = get_route(dpid_1, puerto_1, dpid_2, puerto_2)
    print(ruta)
    if isinstance(ruta, str):  # Si la función retorna un mensaje de error
        print(f"Error al obtener la ruta: {ruta}")
        return
    
    # Paso 3: Configurar las reglas en cada switch de la ruta
    pusher = StaticFlowPusher(controller_ip)
    
    for switch, puerto_entrada, puerto_salida in ruta:
        # Flujo de controlador a H3 (filtrado por MAC de origen y destino, TCP, ICMP y ARP)
        flujo_host_portal = {
            "switch": switch,
            "name": f"flow_{switch}_ctrl2h3",
            "cookie": "0",
            "priority": "32768",
            "actions": f"output={puerto_salida}",
            "match": {
                "eth_type": "0x0800",  # IPv4
                "ipv4_src": host_ip,  # IP del controlador
                "ipv4_dst": portal_ip,  # IP del host H3
                "eth_src": mac_1,  # MAC de origen (controlador)
                "eth_dst": mac_2,  # MAC de destino (H3)
                "ip_proto": "0x06",  # TCP (filtrado para tráfico TCP)
                "tcp_dst": "80"  # Puerto 80 como ejemplo (puedes modificar según sea necesario)
            }
        }
        
        # Flujo de H3 a controlador (filtrado por MAC de origen y destino, TCP, ICMP y ARP)
        flujo_portal_host = {
            "switch": switch,
            "name": f"flow_{switch}_h32ctrl",
            "cookie": "0",
            "priority": "32768",
            "actions": f"output={puerto_entrada}",
            "match": {
                "eth_type": "0x0800",  # IPv4
                "ipv4_src": portal_ip,  # IP del host H3
                "ipv4_dst": host_ip,  # IP del controlador
                "eth_src": mac_2,  # MAC de origen (H3)
                "eth_dst": mac_1,  # MAC de destino (controlador)
                "ip_proto": "0x06",  # TCP (filtrado para tráfico TCP)
                "tcp_src": "80"  # Puerto 80 como ejemplo (puedes modificar según sea necesario)
            }
        }

        # Flujo de controlador a H3 para ICMP (Protocolo 1)
        flujo_host_portal_icmp = {
            "switch": switch,
            "name": f"flow_{switch}_ctrl2h3_icmp",
            "cookie": "0",
            "priority": "32768",
            "actions": f"output={puerto_salida}",
            "match": {
                "eth_type": "0x0800",  # IPv4
                "ipv4_src": host_ip,  # IP del controlador
                "ipv4_dst": portal_ip,  # IP del host H3
                "eth_src": mac_1,  # MAC de origen (controlador)
                "eth_dst": mac_2,  # MAC de destino (H3)
                "ip_proto": "0x01"  # ICMP (Protocolo 1)
            }
        }

        # Flujo de H3 a controlador para ICMP (Protocolo 1)
        flujo_portal_host_icmp = {
            "switch": switch,
            "name": f"flow_{switch}_h32ctrl_icmp",
            "cookie": "0",
            "priority": "32768",
            "actions": f"output={puerto_entrada}",
            "match": {
                "eth_type": "0x0800",  # IPv4
                "ipv4_src": portal_ip,  # IP del host H3
                "ipv4_dst": host_ip,  # IP del controlador
                "eth_src": mac_2,  # MAC de origen (H3)
                "eth_dst": mac_1,  # MAC de destino (controlador)
                "ip_proto": "0x01"  # ICMP (Protocolo 1)
            }
        }

        # Flujo de controlador a H3 para ARP (Protocolo 0x0806)
        flujo_host_portal_arp = {
            "switch": switch,
            "name": f"flow_{switch}_ctrl2h3_arp",
            "cookie": "0",
            "priority": "32768",
            "actions": f"output={puerto_salida}",
            "match": {
                "eth_type": "0x0806",  # ARP
                "arp_spa": host_ip,  # MAC de origen (controlador)
                "arp_tpa": portal_ip,  # MAC de destino (H3)
            }
        }

        # Flujo de H3 a controlador para ARP (Protocolo 0x0806)
        flujo_portal_host_arp = {
            "switch": switch,
            "name": f"flow_{switch}_h32ctrl_arp",
            "cookie": "0",
            "priority": "32768",
            "actions": f"output={puerto_entrada}",
            "match": {
                "eth_type": "0x0806",  # ARP
                "arp_spa": portal_ip,  # MAC de origen (H3)
                "arp_tpa": host_ip,  # MAC de destino (controlador)
            }
        }

        # Configuración de los flujos en el switch
        print(f"Configurando flujo Controlador -> H3 (TCP) en el switch {switch}")
        pusher.set(flujo_host_portal)
        
        print(f"Configurando flujo Controlador -> H3 (ICMP) en el switch {switch}")
        pusher.set(flujo_host_portal_icmp)
        
        print(f"Configurando flujo Controlador -> H3 (ARP) en el switch {switch}")
        pusher.set(flujo_host_portal_arp)
        
        print(f"Configurando flujo H3 -> Controlador (TCP) en el switch {switch}")
        pusher.set(flujo_portal_host)
        
        print(f"Configurando flujo H3 -> Controlador (ICMP) en el switch {switch}")
        pusher.set(flujo_portal_host_icmp)
        
        print(f"Configurando flujo H3 -> Controlador (ARP) en el switch {switch}")
        pusher.set(flujo_portal_host_arp)

    
    print("Reglas configuradas exitosamente para la comunicación entre el controlador y H3.")

def trafico_a_freeradius():
    # Paso 1: Obtener los datos de conexión para los dispositivos
    resultado = obtener_puntos_conexion_ip(portal_ip, freeradius_ip)
    if resultado is None:
        print("No se pudieron obtener los puntos de conexión.")
        return
    
    mac_1, dpid_1, puerto_1, mac_2, dpid_2, puerto_2 = resultado
    
    if not dpid_1 or not dpid_2:
        print("No se pudo determinar los puntos de conexión del H1 y H2.")
        return
    
    # Paso 2: Obtener la ruta entre el controlador y FreeRADIUS
    ruta = get_route(dpid_1, puerto_1, dpid_2, puerto_2)
    print(ruta)
    if isinstance(ruta, str):  # Si la función retorna un mensaje de error
        print(f"Error al obtener la ruta: {ruta}")
        return
    
    # Paso 3: Configurar las reglas en cada switch de la ruta
    pusher = StaticFlowPusher(controller_ip)
    
    for switch, puerto_entrada, puerto_salida in ruta:
        # Flujo de portal (controlador) a FreeRADIUS (filtrado por MAC de origen y destino)
        flujo_portal_freeradius = {
            "switch": switch,
            "name": f"flow_{switch}_portal2radius",
            "cookie": "0",
            "priority": "32768",
            "actions": f"output={puerto_salida}",
            "match": {
                "eth_type": "0x0800",  # IPv4
                "ipv4_src": portal_ip,  # IP del portal (controlador)
                "ipv4_dst": freeradius_ip,  # IP del servidor FreeRADIUS
                "eth_src": mac_1,  # MAC de origen (controlador)
                "eth_dst": mac_2,  # MAC de destino (FreeRADIUS)
                "ip_proto": "0x11",  # UDP (filtrado para tráfico UDP)
                "udp_dst": "1812"  # Puerto 1812 (autenticación RADIUS)
            }
        }
        
        # Flujo de FreeRADIUS a portal (controlador) (filtrado por MAC de origen y destino)
        flujo_freeradius_portal = {
            "switch": switch,
            "name": f"flow_{switch}_radius2portal",
            "cookie": "0",
            "priority": "32768",
            "actions": f"output={puerto_entrada}",
            "match": {
                "eth_type": "0x0800",  # IPv4
                "ipv4_src": freeradius_ip,  # IP del servidor FreeRADIUS
                "ipv4_dst": portal_ip,  # IP del portal (controlador)
                "eth_src": mac_2,  # MAC de origen (FreeRADIUS)
                "eth_dst": mac_1,  # MAC de destino (controlador)
                "ip_proto": "0x11",  # UDP (filtrado para tráfico UDP)
                "udp_src": "1812"  # Puerto 1812 (autenticación RADIUS)
            }
        }

        # Flujo para la contabilización de RADIUS (puerto 1813)
        flujo_portal_freeradius_contabilizacion = {
            "switch": switch,
            "name": f"flow_{switch}_portal2radius_contabilizacion",
            "cookie": "0",
            "priority": "32768",
            "actions": f"output={puerto_salida}",
            "match": {
                "eth_type": "0x0800",  # IPv4
                "ipv4_src": portal_ip,  # IP del portal (controlador)
                "ipv4_dst": freeradius_ip,  # IP del servidor FreeRADIUS
                "eth_src": mac_1,  # MAC de origen (controlador)
                "eth_dst": mac_2,  # MAC de destino (FreeRADIUS)
                "ip_proto": "0x11",  # UDP (filtrado para tráfico UDP)
                "udp_dst": "1813"  # Puerto 1813 (contabilización RADIUS)
            }
        }
        
        # Flujo de FreeRADIUS a portal para contabilización
        flujo_freeradius_portal_contabilizacion = {
            "switch": switch,
            "name": f"flow_{switch}_radius2portal_contabilizacion",
            "cookie": "0",
            "priority": "32768",
            "actions": f"output={puerto_entrada}",
            "match": {
                "eth_type": "0x0800",  # IPv4
                "ipv4_src": freeradius_ip,  # IP del servidor FreeRADIUS
                "ipv4_dst": portal_ip,  # IP del portal (controlador)
                "eth_src": mac_2,  # MAC de origen (FreeRADIUS)
                "eth_dst": mac_1,  # MAC de destino (controlador)
                "ip_proto": "0x11",  # UDP (filtrado para tráfico UDP)
                "udp_src": "1813"  # Puerto 1813 (contabilización RADIUS)
            }
        }

        flujo_portal_freeradius_icmp = {
            "switch": switch,
            "name": f"flow_{switch}_portal2radius_icmp",
            "cookie": "0",
            "priority": "32768",
            "actions": f"output={puerto_salida}",
            "match": {
                "eth_type": "0x0800",  # IPv4
                "ipv4_src": portal_ip,  # IP del portal (controlador)
                "ipv4_dst": freeradius_ip,  # IP del servidor FreeRADIUS
                "ip_proto": "0x01"  # ICMP
            }
        }

        flujo_freeradius_portal_icmp = {
            "switch": switch,
            "name": f"flow_{switch}_radius2portal_icmp",
            "cookie": "0",
            "priority": "32768",
            "actions": f"output={puerto_entrada}",
            "match": {
                "eth_type": "0x0800",  # IPv4
                "ipv4_src": freeradius_ip,  # IP del servidor FreeRADIUS
                "ipv4_dst": portal_ip,  # IP del portal (controlador)
                "ip_proto": "0x01"  # ICMP
            }
        }


        flujo_portal_freeradius_arp = {
            "switch": switch,
            "name": f"flow_{switch}_portal2radius_arp",
            "cookie": "0",
            "priority": "32768",
            "actions": f"output={puerto_salida}",
            "match": {
                "eth_type": "0x0806",  # ARP
                "arp_spa": portal_ip,  # Dirección IP del portal (controlador)
                "arp_tpa": freeradius_ip,  # Dirección IP del servidor FreeRADIUS
            }
        }

        flujo_freeradius_portal_arp = {
            "switch": switch,
            "name": f"flow_{switch}_radius2portal_arp",
            "cookie": "0",
            "priority": "32768",
            "actions": f"output={puerto_entrada}",
            "match": {
                "eth_type": "0x0806",  # ARP
                "arp_spa": freeradius_ip,  # Dirección IP del servidor FreeRADIUS
                "arp_tpa": portal_ip,  # Dirección IP del portal (controlador)
            }
        }

        flujo_portal_mysql = {
            "switch": switch,
            "name": f"flow_{switch}_portal2mysql",
            "cookie": "0",
            "priority": "32768",
            "actions": f"output={puerto_salida}",
            "match": {
                "eth_type": "0x0800",  # IPv4
                "ipv4_src": portal_ip,  # IP del portal (controlador)
                "ipv4_dst": freeradius_ip,  # IP del servidor (también donde está MySQL)
                "ip_proto": "0x06",  # TCP
                "tcp_dst": "3306"  # Puerto de MySQL
            }
        }

        flujo_mysql_portal = {
            "switch": switch,
            "name": f"flow_{switch}_mysql2portal",
            "cookie": "0",
            "priority": "32768",
            "actions": f"output={puerto_entrada}",
            "match": {
                "eth_type": "0x0800",  # IPv4
                "ipv4_src": freeradius_ip,  # IP del servidor (MySQL)
                "ipv4_dst": portal_ip,  # IP del portal (controlador)
                "ip_proto": "0x06",  # TCP
                "tcp_src": "3306"  # Puerto de MySQL
            }
        }



        # Insertar las reglas en los switches
        print(f"Configurando flujo Portal -> FreeRADIUS (autenticación) en el switch {switch}")
        pusher.set(flujo_portal_freeradius)
        
        print(f"Configurando flujo FreeRADIUS -> Portal (autenticación) en el switch {switch}")
        pusher.set(flujo_freeradius_portal)
        
        print(f"Configurando flujo Portal -> FreeRADIUS (contabilización) en el switch {switch}")
        pusher.set(flujo_portal_freeradius_contabilizacion)
        
        print(f"Configurando flujo FreeRADIUS -> Portal (contabilización) en el switch {switch}")
        pusher.set(flujo_freeradius_portal_contabilizacion)

        pusher.set(flujo_portal_freeradius_icmp)
        pusher.set(flujo_freeradius_portal_icmp)
        pusher.set(flujo_portal_freeradius_arp)
        pusher.set(flujo_freeradius_portal_arp)

        # Reglas para MySQL (Portal -> MySQL y MySQL -> Portal)
        print(f"Configurando flujo Portal -> MySQL en el switch {switch}")
        pusher.set(flujo_portal_mysql)

        print(f"Configurando flujo MySQL -> Portal en el switch {switch}")
        pusher.set(flujo_mysql_portal)

    
    print("Reglas configuradas exitosamente para la comunicación entre el portal y FreeRADIUS.")

# Función para establecer la conexión
def establecer_conexion():
    codigo_alumno = input("Ingresa el código del alumno: ").strip()
    alumno_encontrado = next((alumno for alumno in alumnos if str(alumno.codigo).strip() == codigo_alumno), None)
    if not alumno_encontrado:
        print(f"No se encontró ningún alumno con el código '{codigo_alumno}'.")
        return 
    print(f"Alumno encontrado: {alumno_encontrado.nombre}")  
    nombre_servidor = input("Ingresa el nombre del servidor: ").strip()  
    servidor_encontrado = next((servidor for servidor in servidores if servidor.nombre == nombre_servidor), None)  
    if not servidor_encontrado:
        print(f"No se encontró ningún servidor con el nombre '{nombre_servidor}'.")
        return   
    conexion_existente = next(
        (conexion for conexion in conexiones 
         if conexion['alumno'] == alumno_encontrado.nombre and conexion['servidor'] == nombre_servidor),
        None
    )   
    if not conexion_existente:
        print(f"No existe una conexión creada entre el alumno '{alumno_encontrado.nombre}' y el servidor '{nombre_servidor}'.")
        return   
    cursos_validos = [
        curso for curso in cursos 
        if any(srv.nombre == nombre_servidor for srv in curso.servidores) and 
        any(str(alumno.codigo) == codigo_alumno for alumno in curso.alumnos) and
        curso.estado == "DICTANDO"
    ]    
    if not cursos_validos:
        print(f"El alumno '{alumno_encontrado.nombre}' no pertenece a un curso activo con acceso al servidor '{nombre_servidor}'.")
        return    
    print(f"La conexión entre el alumno '{alumno_encontrado.nombre}' y el servidor '{nombre_servidor}' es válida.")
    print("Conexión establecida exitosamente.")

# Función para añadir un Curso
def añadir_curso():
    nombre = input("Ingresa el nombre del curso: ")
    estado = input("Ingresa el estado del curso (Activo/Inactivo): ")
    curso = Curso(nombre, estado)
    cursos.append(curso)  # Añadir el curso a la lista
    print(f"Curso {nombre} añadido.")



# Función para añadir un Servidor
def añadir_servidor():
    nombre = input("Ingresa el nombre del servidor: ")
    direccion_ip = input("Ingresa la dirección IP del servidor: ")
    servidor = Servidor(nombre, direccion_ip)
    servidores.append(servidor)  # Añadir el servidor a la lista
    print(f"Servidor {nombre} añadido.")



# Función para listar todos los cursos

      
# Función para listar todos los datos
def listar_datos():
    print("\nListado de Alumnos:")
    for alumno in alumnos:
        print(f"Nombre: {alumno.nombre}, MAC: {alumno.mac}")
        
    print("\nListado de Cursos:")
    for curso in cursos:
        print(f"Nombre: {curso.nombre}, Estado: {curso.estado}")
        
    print("\nListado de Servidores:")
    for servidor in servidores:
        print(f"Nombre: {servidor.nombre}, IP: {servidor.ip}")

# Función para validar acceso de un alumno a un servicio
def validar_acceso_usuario():
    # Solicitar datos al usuario para realizar la validación
    mac_alumno = input("Ingresa la dirección MAC del alumno: ").strip()
    curso = input("Ingresa el nombre del curso: ").strip()

    # Lógica para validar el acceso...
    print(f"Validando acceso para {mac_alumno} en el curso {curso}...")

# Función para ver ruta entre dispositivos
def ver_ruta_conexion():
    # Lógica para mostrar la ruta entre dispositivos...
    print("Mostrando ruta de conexión entre dispositivos...")

# Función para instalar una ruta entre dispositivos
def instalar_ruta_conexion():
    # Lógica para instalar ruta...
    print("Instalando ruta entre dispositivos...")

# Función para validar si la MAC es válida
def es_mac_valida(mac):
    pattern = r"^[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}$"
    return bool(re.match(pattern, mac))

# Función para arrancar el servidor Flask
def arrancar_servidor():
    global server_running
    if server_running:
        print("⚠️ El servidor ya está en ejecución.")
        return
    
    def run_server():
        try:
            
            print("\nIniciando servidor API en puerto:", SERVER_PORT)
            app.run(host='0.0.0.0', port=SERVER_PORT, debug=False, use_reloader=False)
        except Exception as e:
            print(f"Error al iniciar el servidor: {e}")

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    server_running = True

# Inicio del programa
if __name__ == "__main__":
    mostrar_menu_principal()

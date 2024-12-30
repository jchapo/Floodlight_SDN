from flask import Flask, render_template, request, flash, redirect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from pyrad.client import Client
from pyrad.packet import AccessRequest, AccessAccept
from pyrad.dictionary import Dictionary
import logging
import pymysql
import requests  # Importar requests para enviar datos al programa en la red LAN

# Configuración básica del logger
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = 'clave_secreta_para_sesion'

# Configuración de FreeRADIUS
RADIUS_SERVER = '10.0.0.3'
RADIUS_SECRET = 'passfreeradius'
RADIUS_PORT = 1812
RADIUS_DICT_PATH = '/etc/freeradius/3.0/dictionary'

# Configuración de MySQL
DB_HOST = '10.0.0.3'
DB_USER = 'root'
DB_PASSWORD = 'password'
DB_NAME = 'radius'

# Configuración de Flask-Limiter
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],  # Límite global: 3 solicitudes cada 5 minutos
)

# Lista para controlar las IPs activas
active_ips = set()

# Configuración del programa en la red LAN
CONTROLLER_URL = 'http://10.8.0.65:8083'  # Cambia si es necesario

@app.route('/', methods=['GET', 'POST'])
@limiter.limit("3 per 1 minute", methods=['POST'], key_func=get_remote_address)
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        client_ip = request.remote_addr
        logger.info(f"Inicio de sesión desde la IP: {client_ip}")

        # Verificar si hay demasiadas IPs activas
        if len(active_ips) >= 3 and client_ip not in active_ips:
            flash('Se ha alcanzado el límite de IPs activas.', 'danger')
            return render_template('login.html')

        if authenticate_with_radius(username, password, client_ip):
            active_ips.add(client_ip)  # Añadir IP a la lista de IPs activas
            flash('Autenticación exitosa', 'success')
            
            user_data = get_user_courses(username)
            flow_message = "No se han insertado reglas de flujo."  # Mensaje por defecto si no se insertaron flujos

            if user_data:
                # Enviar datos al controlador SDN
                try:
                    response = requests.post(
                        f'{CONTROLLER_URL}/configure_flows',
                        json={
                            'username': username,
                            'client_ip': client_ip,
                            'courses': user_data
                        }
                    )
                    if response.status_code == 200:
                        logger.info("Flujos configurados exitosamente")
                        flow_message = "Flujos configurados exitosamente"
                    else:
                        logger.error(f"Error al configurar flujos: {response.status_code}")
                        flow_message = f"Error al configurar flujos: {response.status_code}"
                except requests.exceptions.RequestException as e:
                    logger.error(f"Error al comunicarse con el controlador SDN: {e}")
                    flow_message = f"Error al comunicarse con el controlador SDN: {e}"

                return render_template('success.html', user_data=user_data, client_ip=client_ip, flow_message=flow_message)
            else:
                flash('No se encontraron datos para este usuario.', 'info')
                return render_template('success.html', user_data=None, client_ip=client_ip, flow_message=flow_message)
        else:
            flash('Credenciales inválidas', 'danger')
    
    return render_template('login.html')

@app.route('/logout', methods=['POST'])
def logout():
    # Obtener la IP del cliente para eliminarla de la lista de IPs activas
    client_ip = request.remote_addr
    active_ips.discard(client_ip)  # Eliminar IP de la lista de IPs activas
    flash('Sesión cerrada correctamente.', 'success')
    return redirect('/')

@app.route('/success', methods=['GET'])
def success():
    return render_template('success.html', user_data=None, client_ip=None)

@app.errorhandler(429)
def ratelimit_error(e):
    return render_template('429.html'), 429

def authenticate_with_radius(username, password, client_ip=None):
    try:
        # Crear cliente RADIUS
        client = Client(
            server=RADIUS_SERVER, 
            secret=RADIUS_SECRET.encode(), 
            dict=Dictionary(RADIUS_DICT_PATH)
        )
        
        # Configurar puerto
        client.AuthPort = RADIUS_PORT
        
        # Crear paquete de autenticación
        request = client.CreateAuthPacket(code=AccessRequest)
        
        # Añadir atributos de autenticación
        request.AddAttribute('User-Name', username)
        request.AddAttribute('Cleartext-Password', password)
        
        # Registrar la dirección IP como atributo opcional
        if client_ip:
            request.AddAttribute('Calling-Station-Id', client_ip)
        
        # Enviar paquete y recibir respuesta
        response = client.SendPacket(request)

        # Verificar si la autenticación fue exitosa
        return response.code == AccessAccept
    
    except Exception as e:
        logger.error(f"Error detallado de autenticación RADIUS: {type(e)}")
        logger.error(f"Detalles del error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

def get_user_courses(username):
    try:
        # Establecer conexión con la base de datos
        connection = pymysql.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME
        )
        try:
            with connection.cursor() as cursor:
                query = """
                SELECT c.servidor_ip, c.puerto, c.servicio, c.nombre_curso 
                FROM cursos c
                JOIN usuario_cursos uc ON c.id = uc.curso_id
                WHERE uc.username = %s
                """
                cursor.execute(query, (username,))
                results = cursor.fetchall()
                if not results:
                    logger.info(f"No se encontraron datos para el usuario: {username}")
                return results
        finally:
            connection.close()
    except pymysql.MySQLError as e:
        logger.error(f"Error MySQL: {e}")
        return None
    except Exception as e:
        logger.error(f"Error desconocido al obtener datos de usuario: {e}")
        return None

if __name__ == '__main__':
    app.run(host='10.0.0.2', port=80, debug=True)

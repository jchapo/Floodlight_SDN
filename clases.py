# clases.py

import http.client
import json

class StaticFlowPusher(object):
    def __init__(self, server):
        self.server = server

    def get(self, data):
        ret = self.rest_call({}, 'GET')
        return json.loads(ret[2])

    def set(self, data):
        ret = self.rest_call(data, 'POST')
        return ret[0] == 200

    def remove(self, objtype, data):
        ret = self.rest_call(data, 'DELETE')
        return ret[0] == 200

    def rest_call(self, data, action):
        path = '/wm/staticflowpusher/json'
        headers = {
            'Content-type': 'application/json',
            'Accept': 'application/json',
        }
        body = json.dumps(data)  # Esto usa json para convertir el objeto a JSON
        conn = http.client.HTTPConnection(self.server, 8080)  # Cambiado httplib a http.client
        conn.request(action, path, body, headers)
        response = conn.getresponse()
        ret = (response.status, response.reason, response.read())
        # print(ret)
        conn.close()
        return ret

    
class Alumno:
    def __init__(self, nombre, codigo, mac):
        self.nombre = nombre
        self.codigo = codigo
        self.mac = mac

    def __str__(self):
        return f"Alumno: {self.nombre}, Código: {self.codigo}, MAC: {self.mac}"

class Servidor:
    def __init__(self, nombre, ip):
        self.nombre = nombre
        self.ip = ip
        self.servicios = []

    def agregar_servicio(self, servicio):
        self.servicios.append(servicio)

    def __str__(self):
        return f"Servidor: {self.nombre}, IP: {self.ip}, Servicios: {[str(servicio) for servicio in self.servicios]}"

class Servicio:
    def __init__(self, nombre, protocolo, puerto):
        self.nombre = nombre
        self.protocolo = protocolo
        self.puerto = puerto

    def __str__(self):
        return f"Servicio: {self.nombre}, Protocolo: {self.protocolo}, Puerto: {self.puerto}"

class Curso:
    def __init__(self, codigo, estado, nombre):
        self.codigo = codigo
        self.estado = estado
        self.nombre = nombre
        self.alumnos = []
        self.servidores = []
        self.servicios_permitidos = []  # Agregar esta línea para almacenar los servicios permitidos

    def agregar_alumno(self, alumno):
        self.alumnos.append(alumno)

    def agregar_servidor(self, servidor):
        self.servidores.append(servidor)

    def agregar_servicio_permitido(self, servicio):
        self.servicios_permitidos.append(servicio)

    def __str__(self):
        return f"Curso: {self.nombre}, Código: {self.codigo}, Estado: {self.estado}, Alumnos: {len(self.alumnos)}, Servidores: {len(self.servidores)}"

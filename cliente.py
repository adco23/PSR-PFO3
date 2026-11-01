import getpass
import itertools
import json
import queue
import socket
import threading
import time

HOST = "127.0.0.1"
PORT = 5001
TIMEOUT = 15

sock = None
token = None
contador_ids = itertools.count(1)
pendientes = {}  # id -> queue.Queue donde llega la respuesta
pendientes_lock = threading.Lock()
saliendo = threading.Event()


def recibir_respuestas():
    """Hilo que lee las respuestas del servidor y las entrega al pedido que espera."""
    try:
        with sock.makefile("r", encoding="utf-8") as lector:
            for linea in lector:
                respuesta = json.loads(linea)
                with pendientes_lock:
                    espera = pendientes.pop(respuesta.get("id"), None)
                if espera:
                    espera.put(respuesta)
    except (OSError, ValueError):
        pass
    if not saliendo.is_set():
        print("\n[!] Se perdió la conexión con el servidor.")


def enviar_pedido(tipo, datos=None):
    """Envía un pedido sin esperar la respuesta. Devuelve la cola donde llegará."""
    pedido_id = next(contador_ids)
    espera = queue.Queue(maxsize=1)
    with pendientes_lock:
        pendientes[pedido_id] = espera

    pedido = {"id": pedido_id, "tipo": tipo, "token": token, "datos": datos or {}}
    sock.sendall((json.dumps(pedido, ensure_ascii=False) + "\n").encode("utf-8"))
    return espera


def esperar_respuesta(espera):
    try:
        return espera.get(timeout=TIMEOUT)
    except queue.Empty:
        return {"estado": "error", "error": "El servidor tardó demasiado en responder"}


def enviar(tipo, datos=None):
    """Envía un pedido, espera la respuesta y la muestra."""
    try:
        respuesta = esperar_respuesta(enviar_pedido(tipo, datos))
    except OSError:
        respuesta = {"estado": "error", "error": "No hay conexión con el servidor"}
    mostrar_respuesta(respuesta)
    return respuesta


def mostrar_respuesta(respuesta):
    estado = "OK" if respuesta.get("estado") == "ok" else "ERROR"
    mensaje = respuesta.get("mensaje") or respuesta.get("error") or ""
    worker = respuesta.get("worker", "-")
    if mensaje:
        print(f"[{estado} | {worker}] {mensaje}")


def pedir_credenciales():
    usuario = input("Usuario: ").strip()
    contraseña = getpass.getpass("Contraseña: ")
    return {"usuario": usuario, "contraseña": contraseña}


def pedir_id_tarea():
    try:
        return int(input("ID de la tarea: ").strip())
    except ValueError:
        print("El ID debe ser un número.")
        return None


def registrar():
    enviar("registro", pedir_credenciales())


def iniciar_sesion():
    global token
    respuesta = enviar("login", pedir_credenciales())
    if respuesta.get("estado") == "ok":
        token = respuesta["token"]


def crear_tarea():
    titulo = input("Título: ").strip()
    descripcion = input("Descripción (opcional): ").strip()
    enviar("crear_tarea", {"titulo": titulo, "descripcion": descripcion})


def ver_tareas():
    respuesta = enviar("listar_tareas")
    if respuesta.get("estado") != "ok":
        return

    tareas = respuesta["tareas"]
    print(f"[OK | {respuesta['worker']}] {len(tareas)} tarea(s)")
    for t in tareas:
        marca = "x" if t["completada"] else " "
        detalle = f" - {t['descripcion']}" if t["descripcion"] else ""
        print(f"  [{marca}] {t['id']}. {t['titulo']}{detalle}")


def completar_tarea():
    tarea_id = pedir_id_tarea()
    if tarea_id is not None:
        enviar("completar_tarea", {"tarea_id": tarea_id})


def eliminar_tarea():
    tarea_id = pedir_id_tarea()
    if tarea_id is not None:
        enviar("eliminar_tarea", {"tarea_id": tarea_id})


def reportes_en_paralelo():
    """Envía varios reportes (tareas lentas) juntos para ver trabajar a los workers."""
    try:
        cantidad = int(input("¿Cuántos reportes enviar a la vez? ").strip())
    except ValueError:
        print("Debe ser un número.")
        return

    inicio = time.time()
    try:
        esperas = [enviar_pedido("generar_reporte") for _ in range(cantidad)]
    except OSError:
        print("No hay conexión con el servidor.")
        return
    print(f"{cantidad} reportes enviados, esperando resultados...")

    for espera in esperas:
        respuesta = esperar_respuesta(espera)
        transcurrido = time.time() - inicio
        if respuesta.get("estado") == "ok":
            r = respuesta["reporte"]
            print(f"  [{transcurrido:4.1f}s | {respuesta['worker']}] "
                  f"total={r['total']} completadas={r['completadas']} pendientes={r['pendientes']}")
        else:
            print(f"  [{transcurrido:4.1f}s | {respuesta.get('worker', '-')}] ERROR: {respuesta['error']}")

    print(f"Tiempo total: {time.time() - inicio:.1f}s")


def cerrar_sesion():
    global token
    enviar("logout")
    token = None


def menu():
    opciones = {
        "1": ("Registrarse", registrar),
        "2": ("Iniciar sesión", iniciar_sesion),
        "3": ("Crear tarea", crear_tarea),
        "4": ("Ver tareas", ver_tareas),
        "5": ("Completar tarea", completar_tarea),
        "6": ("Eliminar tarea", eliminar_tarea),
        "7": ("Generar reportes en paralelo", reportes_en_paralelo),
        "8": ("Cerrar sesión", cerrar_sesion),
    }

    while True:
        print("\n--- Cliente de tareas (sockets) ---")
        for clave, (texto, _) in opciones.items():
            print(f"{clave}. {texto}")
        print("9. Salir")

        eleccion = input("Elegí una opción: ").strip()

        if eleccion == "9":
            print("¡Hasta luego!")
            break
        elif eleccion in opciones:
            opciones[eleccion][1]()
        else:
            print("Opción inválida, probá de nuevo.")


def main():
    global sock
    try:
        sock = socket.create_connection((HOST, PORT))
    except OSError:
        print("No se pudo conectar con el servidor. ¿Está corriendo servidor.py?")
        return

    threading.Thread(target=recibir_respuestas, daemon=True).start()
    try:
        menu()
    finally:
        saliendo.set()
        sock.close()


if __name__ == "__main__":
    main()

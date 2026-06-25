import regex
import sys

patrones = {
    'COMENTARIO': r'//.*', 
    'RESERVADA': r'\b(WHEN|IF|THEN|ELSE|DO|END|EVERY)\b', 
    'LOGICO': r'\b(AND|OR|NOT)\b', 
    'BOOLEANO': r'\b(TRUE|FALSE|ON|OFF)\b', 
    'ACTUADOR': r'\b(foco|aire|persiana|cerradura|reloj|altavoz|alarma)_[a-zA-Z0-9_]+\b', 
    'SENSOR': r'\b(sensor_temp|sensor_humedad|sensor_luz|sensor_movimiento|sensor_humo)_[a-zA-Z0-9_]+\b', 
    'ATRIBUTO': r'\.(estado|brillo|color|modo|temp_obj|temp_act|posicion|hora|volumen|mute|fecha|mensaje|email_notif|activada)\b', 
    'COMPARACION': r'==|!=|>=|<=|>|<', 
    'ASIGNACION': r'=', 
    'TEMPERATURA': r'(-\d|-10|\d|[1-4]\d|50)°C',
    'PORCENTAJE': r'(\d|[1-9]\d|100)%',
    'ILUMINANCIA': r'(\d|[1-9]\d|[1-9]\d\d|1000)lux',
    'TEXTO': r'"[^"]*"', 
    'NUMERICO': r'\d+',
    'ESPACIO': r'\s+',
    'HORA': r'([0-1]\d|2[0-3]):([0-5]\d)',
    'TIEMPO': r'([0-1]\d|2[0-3])h|([0-5]\d)m|([0-5]\d)',
    'FECHA': r'((0?\d|1\d|2\d|3[0-1])\/(0?\d|1[0-2])\/\d\d?\d?\d?)',
    'EMAIL': r'[a-z0-9.]+@[a-zA-Z_]+?\.[a-zA-Z]{2,4}'
}

# Precompilar los patrones usando nuestro propio motor de regex
compiled_patrones = {}
for nombre, patron in patrones.items():
    infix = regex.tokenize_regex(patron)
    post = regex.re2post(infix)
    start_state = regex.post2nfa(post)
    if start_state is None:
        raise RuntimeError(f"Error al compilar el patrón {nombre}: {patron}")
    compiled_patrones[nombre] = start_state

def lexer_smart_home(codigo: str) -> list:
    tokens = []
    pos = 0
    n = len(codigo)
    while pos < n:
        sub = codigo[pos:]
        longest_len = -1
        best_name = None
        
        # Buscar la coincidencia más larga (Maximal Munch) en la posición actual
        for nombre, start_state in compiled_patrones.items():
            length = regex.match_longest_prefix(start_state, sub, ignore_case=True)
            if length > longest_len:
                longest_len = length
                best_name = nombre
                
        if longest_len <= 0:
            # Si no coincide ningún token, avanzamos un carácter
            pos += 1
            continue
            
        valor = sub[:longest_len]
        
        # Ignoramos espacios y comentarios
        if best_name not in ('ESPACIO', 'COMENTARIO'):
            linea = codigo.count('\n', 0, pos) + 1
            ultima_nueva_linea = codigo.rfind('\n', 0, pos)
            columna = pos + 1 if ultima_nueva_linea == -1 else pos - ultima_nueva_linea
            
            # Normalizar las palabras reservadas a mayúsculas
            if best_name in ('RESERVADA', 'LOGICO', 'BOOLEANO'):
                valor = valor.upper()
            tokens.append((best_name, valor, linea, columna))
            
        pos += longest_len
    return tokens
class ParserSmartHome:
    def __init__(self, tokens, codigo=""):
        self.tokens = tokens
        self.codigo = codigo
        self.pos = 0

    def token_actual(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def obtener_posicion_error(self):
        token = self.token_actual()
        if token:
            return token[2], token[3]
        if self.codigo:
            pos = len(self.codigo)
            linea = self.codigo.count('\n', 0, pos) + 1
            ultima_nueva_linea = self.codigo.rfind('\n', 0, pos)
            columna = pos + 1 if ultima_nueva_linea == -1 else pos - ultima_nueva_linea
            return linea, columna
        if self.tokens:
            ultimo = self.tokens[-1]
            return ultimo[2], ultimo[3]
        return 1, 1

    def consumir(self, tipo_esperado, valor_esperado=None):
        token = self.token_actual()
        if token and token[0] == tipo_esperado:
            if valor_esperado and token[1] != valor_esperado:
                linea, columna = token[2], token[3]
                raise SyntaxError(f"Error de Sintaxis en línea {linea}, columna {columna}: Se esperaba '{valor_esperado}', se encontró '{token[1]}'")
            self.pos += 1
            return token
        
        linea, columna = self.obtener_posicion_error()
        if token:
            raise SyntaxError(f"Error de Sintaxis en línea {linea}, columna {columna}: se esperaba {tipo_esperado}, se encontró '{token[1]}'")
        else:
            raise SyntaxError(f"Error de Sintaxis en línea {linea}, columna {columna}: se esperaba {tipo_esperado} al final del archivo")

    # --- NUEVOS MÉTODOS AUXILIARES ---

    def identificador(self):
        """<identificador> -> <sensores> | <sensores>.<atributos> | <actuadores> | <actuadores>.<atributos>"""
        token = self.token_actual()
        if token and token[0] in ['SENSOR', 'ACTUADOR']:
            dispositivo = self.consumir(token[0])[1]
            atributo = None
            # Verificamos si tiene un atributo (ej: .estado, .temp_obj)
            siguiente = self.token_actual()
            if siguiente and siguiente[0] == 'ATRIBUTO':
                atributo = self.consumir('ATRIBUTO')[1]
            return {"dispositivo": dispositivo, "atributo": atributo}
        
        linea, columna = self.obtener_posicion_error()
        if token:
            raise SyntaxError(f"Error de Sintaxis en línea {linea}, columna {columna}: Se esperaba un SENSOR o ACTUADOR, se encontró '{token[1]}'")
        else:
            raise SyntaxError(f"Error de Sintaxis en línea {linea}, columna {columna}: Se esperaba un SENSOR o ACTUADOR al final del archivo")

    def condicion(self):
        """<condicion> -> <identificador> <comparacion> <literal/identificador> [<logico> <condicion>]"""
        izq = self.identificador()
        operador = self.consumir('COMPARACION')[1]
        
        # El valor de la derecha puede ser un Literal (NUMERICO, BOOLEANO, etc) u otro Identificador
        token_der = self.token_actual()
        if token_der and token_der[0] in ['NUMERICO', 'TEMPERATURA', 'BOOLEANO', 'TEXTO']:
            der = self.consumir(token_der[0])[1]
        elif token_der and token_der[0] in ['SENSOR', 'ACTUADOR']:
            der = self.identificador()
        else:
            linea, columna = self.obtener_posicion_error()
            if token_der:
                raise SyntaxError(f"Error de Sintaxis en línea {linea}, columna {columna}: Valor inválido en condición: '{token_der[1]}'")
            else:
                raise SyntaxError(f"Error de Sintaxis en línea {linea}, columna {columna}: Valor inválido en condición al final del archivo")
            
        nodo_condicion = {"izq": izq, "operador": operador, "der": der}
        
        # Recursividad por si hay un AND, OR, NOT concatenado
        siguiente = self.token_actual()
        if siguiente and siguiente[0] == 'LOGICO':
            logico = self.consumir('LOGICO')[1]
            otra_condicion = self.condicion()
            return {"tipo": "operacion_logica", "logico": logico, "cond1": {"tipo": "condicion_simple", "detalle": nodo_condicion}, "cond2": otra_condicion}
            
        return {"tipo": "condicion_simple", "detalle": nodo_condicion}

    def lista_acciones(self):
        """<lista_acciones> -> <accion> | <lista_acciones> <accion>"""
        acciones = []
        # Seguirá agrupando acciones hasta que encuentre palabras clave de cierre o bifurcación
        while self.token_actual() and self.token_actual()[1] not in ['END', 'ELSE']:
            acciones.append(self.accion())
        return acciones

    def accion(self):
        """<accion> -> <asignacion> | <condicional>"""
        token = self.token_actual()
        if token[1] == 'IF':
            return self.condicional()
        else:
            return self.asignacion()

    def asignacion(self):
        """<asignacion> -> <identificador> = <literal>"""
        objetivo = self.identificador()
        self.consumir('ASIGNACION')
        
        token_valor = self.token_actual()
        if token_valor and token_valor[0] in ['BOOLEANO', 'TEXTO', 'TEMPERATURA', 'NUMERICO']:
            valor = self.consumir(token_valor[0])[1]
            return {"tipo": "asignacion", "objetivo": objetivo, "valor": valor}
        
        linea, columna = self.obtener_posicion_error()
        if token_valor:
            raise SyntaxError(f"Error de Sintaxis en línea {linea}, columna {columna}: Valor literal no válido en asignación: '{token_valor[1]}'")
        else:
            raise SyntaxError(f"Error de Sintaxis en línea {linea}, columna {columna}: Valor literal no válido en asignación al final del archivo")

    # --- LÓGICA DE BLOQUES PRINCIPALES ---

    def bloque_when(self):
        """<bloque_when> -> WHEN <condicion> DO <lista_acciones> END"""
        self.consumir('RESERVADA', 'WHEN')
        condicion = self.condicion()
        self.consumir('RESERVADA', 'DO')
        acciones = self.lista_acciones()
        self.consumir('RESERVADA', 'END')
        
        return {
            "tipo": "bloque_when",
            "condicion": condicion,
            "acciones": acciones
        }

    def condicional(self):
        """<condicional> -> IF <condicion> THEN <lista_acciones> [ELSE <lista_acciones>] END"""
        self.consumir('RESERVADA', 'IF')
        condicion = self.condicion()
        self.consumir('RESERVADA', 'THEN')
        acciones_then = self.lista_acciones()
        
        acciones_else = None
        # Evaluamos la gramática del ELSE opcional
        if self.token_actual() and self.token_actual()[1] == 'ELSE':
            self.consumir('RESERVADA', 'ELSE')
            acciones_else = self.lista_acciones()
            
        self.consumir('RESERVADA', 'END')
        
        return {
            "tipo": "condicional",
            "condicion": condicion,
            "acciones_then": acciones_then,
            "acciones_else": acciones_else
        }

    def condicion_temporal(self):
        """<condicion_temporal> -> HORA | TIEMPO | FECHA"""
        token = self.token_actual()
        if token and token[0] == 'HORA':
            return {"modo": "hora", "valor": self.consumir('HORA')[1]}
        elif token and token[0] == 'TIEMPO':
            return {"modo": "tiempo", "valor": self.consumir('TIEMPO')[1]}
        elif token and token[0] == 'FECHA':
            return {"modo": "fecha", "valor": self.consumir('FECHA')[1]}
        else:
            linea, columna = self.obtener_posicion_error()
            if token:
                raise SyntaxError(f"Error de Sintaxis en línea {linea}, columna {columna}: Se esperaba HORA, TIEMPO o FECHA después de EVERY, se encontró '{token[1]}'")
            else:
                raise SyntaxError(f"Error de Sintaxis en línea {linea}, columna {columna}: Se esperaba HORA, TIEMPO o FECHA después de EVERY al final del archivo")

    def bloque_every(self):
        """<bloque_every> -> EVERY <condicion_temporal> [AND <condicion_temporal>]* DO <lista_acciones> END"""
        self.consumir('RESERVADA', 'EVERY')
        
        condiciones = [self.condicion_temporal()]
        
        # Permitir múltiples condiciones temporales encadenadas con AND
        while self.token_actual() and self.token_actual()[0] == 'LOGICO' and self.token_actual()[1] == 'AND':
            self.consumir('LOGICO', 'AND')
            condiciones.append(self.condicion_temporal())
        
        self.consumir('RESERVADA', 'DO')
        acciones = self.lista_acciones()
        self.consumir('RESERVADA', 'END')
        
        return {
            "tipo": "bloque_every",
            "condiciones": condiciones,
            "acciones": acciones
        }

    def programa(self):
        """Punto de entrada: <programa> -> <instruccion> | <programa> <instruccion>"""
        instrucciones = []
        while self.token_actual() is not None:
            token = self.token_actual()
            if token[1] == 'WHEN':
                instrucciones.append(self.bloque_when())
            elif token[1] == 'EVERY':
                instrucciones.append(self.bloque_every())
            elif token[1] == 'IF':
                instrucciones.append(self.condicional())
            else:
                instrucciones.append(self.accion())
        return instrucciones

# --- FUNCIONES AUXILIARES DE FORMATEO ---

def formatear_identificador(identificador):
    """Convierte el diccionario del identificador en texto plano (ej: sensor_luz.estado)"""
    if isinstance(identificador, dict) and "dispositivo" in identificador:
        texto = identificador["dispositivo"]
        if identificador.get("atributo"):
            texto += f"{identificador['atributo']}"
        return texto
    return str(identificador)

def formatear_condicion(cond):
    """Procesa recursivamente las condiciones simples y las operaciones lógicas (AND, OR)"""
    if cond["tipo"] == "condicion_simple":
        detalle = cond["detalle"]
        izq = formatear_identificador(detalle["izq"])
        der = formatear_identificador(detalle["der"])
        operador = detalle["operador"]
        # Retornamos la condición formateada visualmente como código
        return f"<span style='color: #c0392b; font-family: monospace; background: #eee; padding: 2px 4px; border-radius: 3px;'>{izq} {operador} {der}</span>"
        
    elif cond["tipo"] == "operacion_logica":
        c1 = formatear_condicion(cond["cond1"])
        c2 = formatear_condicion(cond["cond2"])
        logico = cond["logico"]
        return f"({c1} <strong style='color:#2980b9;'>{logico}</strong> {c2})"
    
    return ""

# --- MOTOR PRINCIPAL DE TRADUCCIÓN HTML ---

def procesar_nodos(nodos):
    """Itera sobre una lista de acciones/instrucciones y genera su HTML correspondiente"""
    html_local = ""
    for nodo in nodos:
        
        # 1. TRADUCCIÓN DE ASIGNACIÓN
        if nodo["tipo"] == "asignacion":
            obj = formatear_identificador(nodo["objetivo"])
            html_local += f"""
            <div style='background-color: #fdfefe; border-left: 4px solid #2ecc71; padding: 10px; margin: 10px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.1);'>
                <strong>➔ Acción:</strong> Configurar <code>{obj}</code> a <strong style='color: #27ae60;'>{nodo['valor']}</strong>
            </div>
            """
            
        # 2. TRADUCCIÓN DE CONDICIONAL (IF / THEN / ELSE)
        elif nodo["tipo"] == "condicional":
            cond_html = formatear_condicion(nodo["condicion"])
            then_html = procesar_nodos(nodo["acciones_then"])
            
            else_html = ""
            if nodo.get("acciones_else"):
                else_html = f"""
                <div style='margin-top: 10px; border-top: 1px dashed #e67e22; padding-top: 10px;'>
                    <strong style='color: #d35400;'>SINO (ELSE):</strong>
                    <div style='padding-left: 20px;'>{procesar_nodos(nodo["acciones_else"])}</div>
                </div>
                """
                
            html_local += f"""
            <div style='background-color: #fef9e7; border-left: 4px solid #f39c12; padding: 10px; margin: 10px 0; border-radius: 0 5px 5px 0;'>
                <strong style='color: #d35400;'>? Condicional (IF):</strong> Si se cumple {cond_html} entonces:
                <div style='padding-left: 20px;'>{then_html}</div>
                {else_html}
            </div>
            """
            
        # 3. TRADUCCIÓN DE BLOQUE DE EVENTO (WHEN)
        elif nodo["tipo"] == "bloque_when":
            cond_html = formatear_condicion(nodo["condicion"])
            acciones_html = procesar_nodos(nodo["acciones"])
            
            html_local += f"""
            <div style='background-color: #ebf5fb; border: 2px solid #3498db; border-radius: 8px; padding: 15px; margin-bottom: 25px; box-shadow: 0 4px 6px rgba(0,0,0,0.05);'>
                <h3 style='color: #2980b9; margin-top: 0; border-bottom: 1px solid #a9cce3; padding-bottom: 5px;'>
                    ⚡ Disparador de Evento (WHEN)
                </h3>
                <p><strong>Condición principal:</strong> {cond_html}</p>
                <p><strong>Ejecutar el siguiente bloque:</strong></p>
                <div style='padding-left: 20px; border-left: 3px solid #a9cce3;'>
                    {acciones_html}
                </div>
            </div>
            """

        # 4. TRADUCCIÓN DE BLOQUE TEMPORAL (EVERY)
        elif nodo["tipo"] == "bloque_every":
            acciones_html = procesar_nodos(nodo["acciones"])
            
            condiciones_html = ""
            for cond in nodo["condiciones"]:
                modo = cond["modo"]
                valor = cond["valor"]
                if modo == "hora":
                    descripcion = f"Todos los días a las <strong>{valor}</strong>"
                elif modo == "tiempo":
                    descripcion = f"Cada <strong>{valor}</strong>"
                elif modo == "fecha":
                    descripcion = f"El día <strong>{valor}</strong>"
                else:
                    descripcion = f"<strong>{valor}</strong>"
                condiciones_html += f"<p><strong>• {modo.upper()}:</strong> {descripcion}</p>"
            
            html_local += f"""
            <div style='background-color: #f5eef8; border: 2px solid #8e44ad; border-radius: 8px; padding: 15px; margin-bottom: 25px; box-shadow: 0 4px 6px rgba(0,0,0,0.05);'>
                <h3 style='color: #6c3483; margin-top: 0; border-bottom: 1px solid #d2b4de; padding-bottom: 5px;'>
                    🕐 Programación Temporal (EVERY)
                </h3>
                {condiciones_html}
                <p><strong>Ejecutar el siguiente bloque:</strong></p>
                <div style='padding-left: 20px; border-left: 3px solid #d2b4de;'>
                    {acciones_html}
                </div>
            </div>
            """
            
    return html_local

def generar_html(ast):
    """Ensambla el documento HTML completo"""
    html = [
        "<!DOCTYPE html>",
        "<html lang='es'>",
        "<head>",
        "    <meta charset='UTF-8'>",
        "    <title>Traductor SMART-HOME</title>",
        "</head>",
        "<body style='font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; color: #333; background-color: #f4f6f7;'>",
        "    <div style='background: white; padding: 30px; border-radius: 10px; box-shadow: 0 4px 15px rgba(0,0,0,0.1);'>",
        "        <h1 style='text-align: center; color: #2c3e50; border-bottom: 2px solid #bdc3c7; padding-bottom: 15px;'>",
        "            🏠 Intérprete SMART-HOME",
        "        </h1>",
        "        <div style='margin-top: 20px;'>",
    ]
    
    # Aquí llamamos a la recursividad con la raíz de nuestro Árbol (el programa entero)
    html.append(procesar_nodos(ast))
    
    html.extend([
        "        </div>",
        "    </div>",
        "</body>",
        "</html>"
    ])
    
    return "\n".join(html)

# --- SCRIPT DE PRUEBA ---

def main() -> None:
    if len(sys.argv) > 1:
        archivo = sys.argv[1]
        if ".smart" in archivo:
            try:
                # 1. Extraer contenido del archivo
                with open(archivo, 'r', encoding='utf-8') as src:
                    codigo_fuente = src.read()

                # 2. Análisis Léxico
                tokens = lexer_smart_home(codigo_fuente)
    
                # 3. Análisis Sintáctico
                parser = ParserSmartHome(tokens, codigo_fuente)
                ast = parser.programa()
                
                # 4. Traducción
                resultado_html = generar_html(ast)
                
                # 5. Guardar archivo
                with open("resultado_smart_home.html", "w", encoding="utf-8") as archivo:
                    archivo.write(resultado_html)
                
                print("¡Éxito! Abre 'resultado_smart_home.html' en tu navegador.")
            except SyntaxError as e:
                print(f"Error detectado por el Parser: {e}")
        else:
            print(f"El archivo debe tener la extensión: .smart")
    else: 
        print(f"Se debe proporcionar un archivo para compilar!")

if __name__ == "__main__":
    main()


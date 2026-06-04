#!/usr/bin/env python3
"""
Implementación extendida de expresiones regulares en Python.
Soporta: ( | ) * + ? . \\d \\s \\w \\b [clase] [^clase]

Compila a un AFND y simula el AFND usando el algoritmo de Thompson.
Apto para procesar patrones como los que se encuentran en main.py.
"""
import sys

# Definiciones de clases para predicados de coincidencia de caracteres

class LiteralMatcher:
    def __init__(self, char):
        self.char = char
    def __call__(self, char, ignore_case=False):
        if ignore_case:
            return self.char.lower() == char.lower()
        return self.char == char
    def __repr__(self):
        return self.char

class DigitMatcher:
    def __call__(self, char):
        return char.isdigit()
    def __repr__(self):
        return r'\d'

class WhitespaceMatcher:
    def __call__(self, char):
        return char.isspace()
    def __repr__(self):
        return r'\s'

class WordMatcher:
    def __call__(self, char):
        return char.isalnum() or char == '_'
    def __repr__(self):
        return r'\w'

class DotMatcher:
    def __call__(self, char):
        return char != '\n'
    def __repr__(self):
        return '.'

class WordBoundaryAssertion:
    def __repr__(self):
        return r'\b'

class CharClassMatcher:
    def __init__(self, class_str):
        self.class_str = class_str
        self.negated = False
        if class_str.startswith('^'):
            self.negated = True
            class_str = class_str[1:]
        
        self.ranges = []
        self.chars = set()
        
        i = 0
        while i < len(class_str):
            if i + 2 < len(class_str) and class_str[i+1] == '-':
                start = class_str[i]
                end = class_str[i+2]
                self.ranges.append((start, end))
                i += 3
            else:
                self.chars.add(class_str[i])
                i += 1
                
    def __call__(self, char, ignore_case=False):
        c_val = char.lower() if ignore_case else char
        in_class = False
        
        chars_set = {c.lower() for c in self.chars} if ignore_case else self.chars
        if c_val in chars_set:
            in_class = True
        else:
            for start, end in self.ranges:
                s_val = start.lower() if ignore_case else start
                e_val = end.lower() if ignore_case else end
                if s_val <= c_val <= e_val:
                    in_class = True
                    break
        return not in_class if self.negated else in_class

    def __repr__(self):
        return f"[{self.class_str}]"


def tokenize_regex(re_str):
    """
    Parsea una cadena de expresión regular en átomos infijos.
    """
    atoms = []
    i = 0
    while i < len(re_str):
        char = re_str[i]
        if char == '\\':
            if i + 1 >= len(re_str):
                return None
            next_char = re_str[i+1]
            if next_char == 'd':
                atoms.append(DigitMatcher())
            elif next_char == 's':
                atoms.append(WhitespaceMatcher())
            elif next_char == 'w':
                atoms.append(WordMatcher())
            elif next_char == 'b':
                atoms.append(WordBoundaryAssertion())
            else:
                atoms.append(LiteralMatcher(next_char))  # Literal escapado
            i += 2
        elif char == '[':
            start_idx = i + 1
            end_idx = re_str.find(']', start_idx)
            if end_idx == -1:
                return None
            class_content = re_str[start_idx:end_idx]
            atoms.append(CharClassMatcher(class_content))
            i = end_idx + 1
        elif char == '.':
            atoms.append(DotMatcher())
            i += 1
        elif char in ('(', ')', '|', '*', '+', '?'):
            atoms.append(char)
            i += 1
        else:
            atoms.append(LiteralMatcher(char))
            i += 1
    return atoms


def re2post(infix_atoms):
    """
    Convierte átomos infijos a notación posfija.
    Inserta '.' como operador de concatenación explícito.
    """
    if infix_atoms is None:
        return None
    
    nalt = 0
    natom = 0
    buf = []
    paren = []
    
    for atom in infix_atoms:
        if atom == '(':
            if natom > 1:
                natom -= 1
                buf.append('.')
            paren.append({'nalt': nalt, 'natom': natom})
            nalt = 0
            natom = 0
        elif atom == '|':
            if natom == 0:
                return None
            while natom > 1:
                natom -= 1
                buf.append('.')
            natom = 0
            nalt += 1
        elif atom == ')':
            if not paren:
                return None
            if natom == 0:
                return None
            while natom > 1:
                natom -= 1
                buf.append('.')
            natom = 0
            while nalt > 0:
                buf.append('|')
                nalt -= 1
            p = paren.pop()
            nalt = p['nalt']
            natom = p['natom'] + 1
        elif atom in ('*', '+', '?'):
            if natom == 0:
                return None
            buf.append(atom)
        else:
            if natom > 1:
                natom -= 1
                buf.append('.')
            buf.append(atom)
            natom += 1
            
    if paren:
        return None
    while natom > 1:
        natom -= 1
        buf.append('.')
    while nalt > 0:
        buf.append('|')
        nalt -= 1
        
    return buf


class State:
    Match = 'Match'
    Split = 'Split'
    WordBoundary = 'WordBoundary'

    def __init__(self, c, out=None, out1=None):
        self.c = c
        self.out = out
        self.out1 = out1
        self.lastlist = 0

# El único estado global de coincidencia
matchstate = State(State.Match)


class Frag:
    def __init__(self, start, out_list):
        self.start = start
        self.out = out_list


def patch(out_list, s):
    for state, attr in out_list:
        setattr(state, attr, s)


def post2nfa(postfix_atoms):
    """
    Convierte átomos posfijos a AFND.
    """
    if postfix_atoms is None:
        return None
        
    stack = []
    for atom in postfix_atoms:
        if atom == '.':
            # Concatenar
            e2 = stack.pop()
            e1 = stack.pop()
            patch(e1.out, e2.start)
            stack.append(Frag(e1.start, e2.out))
        elif atom == '|':
            # Alternar
            e2 = stack.pop()
            e1 = stack.pop()
            s = State(State.Split, e1.start, e2.start)
            stack.append(Frag(s, e1.out + e2.out))
        elif atom == '?':
            # Cero o uno
            e = stack.pop()
            s = State(State.Split, e.start, None)
            stack.append(Frag(s, e.out + [(s, 'out1')]))
        elif atom == '*':
            # Cero o más
            e = stack.pop()
            s = State(State.Split, e.start, None)
            patch(e.out, s)
            stack.append(Frag(s, [(s, 'out1')]))
        elif atom == '+':
            # Uno o más
            e = stack.pop()
            s = State(State.Split, e.start, None)
            patch(e.out, s)
            stack.append(Frag(e.start, [(s, 'out1')]))
        elif isinstance(atom, WordBoundaryAssertion):
            s = State(State.WordBoundary)
            stack.append(Frag(s, [(s, 'out')]))
        else:
            s = State(atom)
            stack.append(Frag(s, [(s, 'out')]))

    if not stack:
        return None
    e = stack.pop()
    if stack:
        return None
        
    patch(e.out, matchstate)
    return e.start


class List:
    def __init__(self):
        self.s = []

listid = 0
l1 = List()
l2 = List()


def is_word_char(char):
    return char.isalnum() or char == '_'


def addstate(lst, s, string, index):
    """
    Añade un estado a la lista, siguiendo bifurcaciones y evaluando límites de palabra.
    """
    if s is None or s.lastlist == listid:
        return
    s.lastlist = listid
    if s.c == State.Split:
        addstate(lst, s.out, string, index)
        addstate(lst, s.out1, string, index)
        return
    if s.c == State.WordBoundary:
        prev_is_word = False
        if index > 0:
            prev_is_word = is_word_char(string[index-1])
            
        curr_is_word = False
        if index < len(string):
            curr_is_word = is_word_char(string[index])
            
        if prev_is_word != curr_is_word:
            addstate(lst, s.out, string, index)
        return
    lst.s.append(s)


def startlist(start, lst, string):
    """
    Calcula la lista de estados iniciales.
    """
    global listid
    lst.s = []
    listid += 1
    addstate(lst, start, string, 0)
    return lst


def ismatch(lst):
    return any(s is matchstate for s in lst.s)


def step(clist, char, nlist, string, index, ignore_case=False):
    """
    Avanza el AFND un carácter en el índice especificado hacia nlist.
    """
    global listid
    listid += 1
    nlist.s = []
    for s in clist.s:
        match = False
        if callable(s.c):
            try:
                match = s.c(char, ignore_case=ignore_case)
            except TypeError:
                match = s.c(char)
        elif isinstance(s.c, str):
            if ignore_case:
                match = s.c.lower() == char.lower()
            else:
                match = s.c == char
            
        if match:
            addstate(nlist, s.out, string, index + 1)


def match_nfa(start, string, ignore_case=False):
    """
    Ejecuta la coincidencia usando la simulación del AFND.
    """
    clist = startlist(start, l1, string)
    nlist = l2
    
    for index, char in enumerate(string):
        step(clist, char, nlist, string, index, ignore_case=ignore_case)
        clist, nlist = nlist, clist
        
    return ismatch(clist)


def match_longest_prefix(start, string, ignore_case=False):
    """
    Busca la longitud del prefijo más largo de string que coincide con el AFND.
    Devuelve -1 si ningún prefijo coincide.
    """
    clist = startlist(start, l1, string)
    nlist = l2
    
    longest_match_len = -1
    if ismatch(clist):
        longest_match_len = 0
        
    for index, char in enumerate(string):
        step(clist, char, nlist, string, index, ignore_case=ignore_case)
        clist, nlist = nlist, clist
        if len(clist.s) == 0:
            break
        if ismatch(clist):
            longest_match_len = index + 1
            
    return longest_match_len


class DState:
    """
    Representa un estado AFD: una lista de estados AFND almacenada en caché.
    """
    def __init__(self, nfa_list):
        self.l = nfa_list
        self.next = {}
        self.left = None
        self.right = None


alldstates = None


def listcmp(l1_states, l2_states):
    if len(l1_states) < len(l2_states):
        return -1
    if len(l1_states) > len(l2_states):
        return 1
    for s1, s2 in zip(l1_states, l2_states):
        if id(s1) < id(s2):
            return -1
        elif id(s1) > id(s2):
            return 1
    return 0


def dstate(lst):
    """
    Devuelve el DState en caché para la lista lst, creando uno nuevo si es necesario.
    """
    global alldstates
    sorted_states = sorted(lst.s, key=id)
    
    if alldstates is None:
        alldstates = DState(sorted_states)
        return alldstates
        
    dp = alldstates
    while True:
        cmp = listcmp(sorted_states, dp.l)
        if cmp < 0:
            if dp.left is None:
                dp.left = DState(sorted_states)
                return dp.left
            dp = dp.left
        elif cmp > 0:
            if dp.right is None:
                dp.right = DState(sorted_states)
                return dp.right
            dp = dp.right
        else:
            return dp


def startdstate(start, string):
    return dstate(startlist(start, l1, string))


def nextstate(d, char, string, index, ignore_case=False):
    clist = List()
    clist.s = d.l
    step(clist, char, l1, string, index, ignore_case=ignore_case)
    d.next[char] = dstate(l1)
    return d.next[char]


def match_dfa(start, string, ignore_case=False):
    """
    Ejecuta la simulación del AFD para determinar si coincide con la cadena.
    """
    d = start
    for index, char in enumerate(string):
        if char not in d.next:
            nextstate(d, char, string, index, ignore_case=ignore_case)
        d = d.next[char]
        
    return any(s is matchstate for s in d.l)


def has_boundary(postfix):
    return any(isinstance(atom, WordBoundaryAssertion) for atom in postfix)


def main():
    if len(sys.argv) < 3:
        print("uso: python regex.py [-n | -d] expr_regular cadena...", file=sys.stderr)
        print("opciones:\n  -n   usar simulación AFND (por defecto)\n  -d   usar caché AFD", file=sys.stderr)
        sys.exit(1)

    use_dfa = False
    arg_start = 2
    
    if sys.argv[1] == '-d':
        use_dfa = True
        if len(sys.argv) < 4:
            print("uso: python regex.py [-n | -d] expr_regular cadena...", file=sys.stderr)
            sys.exit(1)
        regexp_str = sys.argv[2]
        arg_start = 3
    elif sys.argv[1] == '-n':
        use_dfa = False
        if len(sys.argv) < 4:
            print("uso: python regex.py [-n | -d] expr_regular cadena...", file=sys.stderr)
            sys.exit(1)
        regexp_str = sys.argv[2]
        arg_start = 3
    else:
        regexp_str = sys.argv[1]

    infix = tokenize_regex(regexp_str)
    if infix is None:
        print(f"error al parsear la expresión regular: {regexp_str}", file=sys.stderr)
        sys.exit(1)

    post = re2post(infix)
    if post is None:
        print(f"estructura de expresión regular incorrecta: {regexp_str}", file=sys.stderr)
        sys.exit(1)

    # La simulación AFD no soporta aserciones de límites de forma contextual
    if use_dfa and has_boundary(post):
        print("aviso: se detectó la aserción de límite \\b; cambiando a simulación AFND", file=sys.stderr)
        use_dfa = False

    start = post2nfa(post)
    if start is None:
        print(f"error en la generación del AFND", file=sys.stderr)
        sys.exit(1)

    if use_dfa:
        for i in range(arg_start, len(sys.argv)):
            # Recrea el estado inicial para diferentes cadenas para manejar el contexto correctamente
            dstart_i = startdstate(start, sys.argv[i])
            if match_dfa(dstart_i, sys.argv[i]):
                print(sys.argv[i])
    else:
        for i in range(arg_start, len(sys.argv)):
            if match_nfa(start, sys.argv[i]):
                print(sys.argv[i])

if __name__ == '__main__':
    main()

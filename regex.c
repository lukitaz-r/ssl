/*
 * Implementación extendida de expresiones regulares en C.
 * Soporta: ( | ) * + ? . \\d \\s \\w \\b [clase] [^clase]
 *
 * Compila a un AFND y simula el AFND usando el algoritmo de Thompson,
 * con almacenamiento en caché opcional para AFD para expresiones sin límites de palabra.
 * 
 * Copyright (c) 2007 Russ Cox.
 * Se puede distribuir bajo la licencia MIT, ver al final del archivo.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/*
 * Representa las clases de coincidencia de estados del AFND
 */
enum
{
	Match = 256,
	Split = 257,
	Any = 258,        /* . */
	Digit = 259,      /* \d */
	Whitespace = 260, /* \s */
	Word = 261,       /* \w */
	Boundary = 262,   /* \b */
	CharClass = 263,  /* [...] */
	Concat = 264      /* Operador de concatenación */
};

typedef struct CharClassData CharClassData;
struct CharClassData
{
	int negated;
	char chars[256];
	int nchars;
	struct {
		char start;
		char end;
	} ranges[128];
	int nranges;
};

typedef struct State State;
struct State
{
	int c;
	State *out;
	State *out1;
	int lastlist;
	CharClassData *cc; /* Se usa solo si c == CharClass */
};

State matchstate = { Match };	/* estado de coincidencia */
int nstate;

/* Asigna e inicializa un Estado */
State*
state(int c, State *out, State *out1)
{
	State *s;
	
	nstate++;
	s = malloc(sizeof *s);
	s->lastlist = 0;
	s->c = c;
	s->out = out;
	s->out1 = out1;
	s->cc = NULL;
	return s;
}

/*
 * Un fragmento de AFND parcialmente construido sin el estado de coincidencia completado.
 */
typedef struct Frag Frag;
typedef union Ptrlist Ptrlist;
struct Frag
{
	State *start;
	Ptrlist *out;
};

Frag
frag(State *start, Ptrlist *out)
{
	Frag n = { start, out };
	return n;
}

union Ptrlist
{
	Ptrlist *next;
	State *s;
};

/* Crea una lista con un único elemento que contiene outp. */
Ptrlist*
list1(State **outp)
{
	Ptrlist *l;
	
	l = (Ptrlist*)outp;
	l->next = NULL;
	return l;
}

/* Conecta la lista de estados en 'out' para que apunten a 'start'. */
void
patch(Ptrlist *l, State *s)
{
	Ptrlist *next;
	
	for(; l; l=next){
		next = l->next;
		l->s = s;
	}
}

/* Une las dos listas l1 y l2, devolviendo la combinación. */
Ptrlist*
append(Ptrlist *l1, Ptrlist *l2)
{
	Ptrlist *oldl1;
	
	oldl1 = l1;
	while(l1->next)
		l1 = l1->next;
	l1->next = l2;
	return oldl1;
}

typedef struct Atom Atom;
struct Atom
{
	int type;
	CharClassData *cc;
};

/* Parsea una cadena de expresión regular en átomos infijos */
int
tokenize_regex(char *re, Atom *atoms, int max_atoms)
{
	int n = 0;
	char *p = re;
	while(*p) {
		if(n >= max_atoms)
			return -1;
		if(*p == '\\') {
			p++;
			if(*p == '\0')
				return -1;
			if(*p == 'd') {
				atoms[n].type = Digit;
				atoms[n].cc = NULL;
			} else if(*p == 's') {
				atoms[n].type = Whitespace;
				atoms[n].cc = NULL;
			} else if(*p == 'w') {
				atoms[n].type = Word;
				atoms[n].cc = NULL;
			} else if(*p == 'b') {
				atoms[n].type = Boundary;
				atoms[n].cc = NULL;
			} else {
				atoms[n].type = *p;
				atoms[n].cc = NULL;
			}
			p++;
		} else if(*p == '[') {
			p++;
			char *start = p;
			while(*p && *p != ']')
				p++;
			if(*p == '\0')
				return -1;
			CharClassData *cc = malloc(sizeof *cc);
			memset(cc, 0, sizeof *cc);
			if(*start == '^') {
				cc->negated = 1;
				start++;
			}
			char *ccp = start;
			while(ccp < p) {
				if(ccp + 2 < p && ccp[1] == '-') {
					cc->ranges[cc->nranges].start = ccp[0];
					cc->ranges[cc->nranges].end = ccp[2];
					cc->nranges++;
					ccp += 3;
				} else {
					cc->chars[cc->nchars++] = *ccp;
					ccp++;
				}
			}
			atoms[n].type = CharClass;
			atoms[n].cc = cc;
			p++; /* omitir ']' */
		} else if(*p == '.') {
			atoms[n].type = Any;
			atoms[n].cc = NULL;
			p++;
		} else {
			atoms[n].type = *p;
			atoms[n].cc = NULL;
			p++;
		}
		n++;
	}
	return n;
}

/* Convierte átomos infijos a notación posfija */
int
re2post_atoms(Atom *infix, int ninfix, Atom *postfix)
{
	int nalt, natom;
	int i;
	int nout = 0;
	struct {
		int nalt;
		int natom;
	} paren[100], *p;
	
	p = paren;
	nalt = 0;
	natom = 0;
	
	for(i = 0; i < ninfix; i++) {
		Atom atom = infix[i];
		switch(atom.type) {
		case '(':
			if(natom > 1) {
				natom--;
				postfix[nout++].type = Concat;
				postfix[nout-1].cc = NULL;
			}
			if(p >= paren + 100)
				return -1;
			p->nalt = nalt;
			p->natom = natom;
			p++;
			nalt = 0;
			natom = 0;
			break;
		case '|':
			if(natom == 0)
				return -1;
			while(natom > 1) {
				natom--;
				postfix[nout++].type = Concat;
				postfix[nout-1].cc = NULL;
			}
			natom = 0;
			nalt++;
			break;
		case ')':
			if(p == paren)
				return -1;
			if(natom == 0)
				return -1;
			while(natom > 1) {
				natom--;
				postfix[nout++].type = Concat;
				postfix[nout-1].cc = NULL;
			}
			natom = 0;
			while(nalt > 0) {
				postfix[nout++].type = '|';
				postfix[nout-1].cc = NULL;
				nalt--;
			}
			p--;
			nalt = p->nalt;
			natom = p->natom;
			natom++;
			break;
		case '*':
		case '+':
		case '?':
			if(natom == 0)
				return -1;
			postfix[nout++] = atom;
			break;
		default:
			if(natom > 1) {
				natom--;
				postfix[nout++].type = Concat;
				postfix[nout-1].cc = NULL;
			}
			postfix[nout++] = atom;
			natom++;
			break;
		}
	}
	if(p != paren)
		return -1;
	while(natom > 1) {
		natom--;
		postfix[nout++].type = Concat;
		postfix[nout-1].cc = NULL;
	}
	while(nalt > 0) {
		postfix[nout++].type = '|';
		postfix[nout-1].cc = NULL;
		nalt--;
	}
	return nout;
}

/* Convierte átomos posfijos a AFND. Devuelve el estado inicial */
State*
post2nfa_atoms(Atom *postfix, int npostfix)
{
	int i;
	Frag stack[1000], *stackp, e1, e2, e;
	State *s;

	#define push(s) *stackp++ = s
	#define pop() *--stackp

	stackp = stack;
	for(i=0; i<npostfix; i++){
		Atom atom = postfix[i];
		switch(atom.type){
		default:
			s = state(atom.type, NULL, NULL);
			if(atom.type == CharClass) {
				s->cc = atom.cc;
			}
			push(frag(s, list1(&s->out)));
			break;
		case Concat:	/* concatenar */
			e2 = pop();
			e1 = pop();
			patch(e1.out, e2.start);
			push(frag(e1.start, e2.out));
			break;
		case '|':	/* alternar */
			e2 = pop();
			e1 = pop();
			s = state(Split, e1.start, e2.start);
			push(frag(s, append(e1.out, e2.out)));
			break;
		case '?':	/* cero o uno */
			e = pop();
			s = state(Split, e.start, NULL);
			push(frag(s, append(e.out, list1(&s->out1))));
			break;
		case '*':	/* cero o más */
			e = pop();
			s = state(Split, e.start, NULL);
			patch(e.out, s);
			push(frag(s, list1(&s->out1)));
			break;
		case '+':	/* uno o más */
			e = pop();
			s = state(Split, e.start, NULL);
			patch(e.out, s);
			push(frag(e.start, list1(&s->out1)));
			break;
		}
	}

	e = pop();
	if(stackp != stack)
		return NULL;

	patch(e.out, &matchstate);
	return e.start;
#undef pop
#undef push
}

typedef struct List List;
struct List
{
	State **s;
	int n;
};
List l1, l2;
static int listid;

int iswordchar(int c)
{
	return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_';
}

void addstate(List*, State*, char*, char*);
void step(List*, int, List*, char*, char*);

/* Calcula la lista de estados iniciales */
List*
startlist(State *start, List *l, char *str)
{
	l->n = 0;
	listid++;
	addstate(l, start, str, str);
	return l;
}

/* Comprueba si la lista de estados contiene una coincidencia. */
int
ismatch(List *l)
{
	int i;

	for(i=0; i<l->n; i++)
		if(l->s[i] == &matchstate)
			return 1;
	return 0;
}

/* Añade s a l, siguiendo bifurcaciones y límites de palabra */
void
addstate(List *l, State *s, char *str, char *p)
{
	if(s == NULL || s->lastlist == listid)
		return;
	s->lastlist = listid;
	if(s->c == Split){
		addstate(l, s->out, str, p);
		addstate(l, s->out1, str, p);
		return;
	}
	if(s->c == Boundary){
		int prev_is_word = 0;
		int curr_is_word = 0;
		if(p > str)
			prev_is_word = iswordchar(*(p-1));
		if(*p != '\0')
			curr_is_word = iswordchar(*p);
		if(prev_is_word != curr_is_word)
			addstate(l, s->out, str, p);
		return;
	}
	l->s[l->n++] = s;
}

/* Comprueba si el estado s coincide con el carácter c */
int
matchchar(State *s, int c)
{
	if(s->c < 256)
		return s->c == c;
	switch(s->c){
	case Any:
		return c != '\n';
	case Digit:
		return c >= '0' && c <= '9';
	case Whitespace:
		return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\v' || c == '\f';
	case Word:
		return iswordchar(c);
	case CharClass:
		{
			CharClassData *cc = s->cc;
			int in_class = 0;
			int i;
			for(i=0; i<cc->nchars; i++) {
				if(cc->chars[i] == c) {
					in_class = 1;
					break;
				}
			}
			if(!in_class) {
				for(i=0; i<cc->nranges; i++) {
					if(c >= cc->ranges[i].start && c <= cc->ranges[i].end) {
						in_class = 1;
						break;
					}
				}
			}
			return cc->negated ? !in_class : in_class;
		}
	}
	return 0;
}

/*
 * Avanza el AFND un paso desde clist pasando el carácter c en el puntero p,
 * para crear el siguiente conjunto de estados nlist.
 */
void
step(List *clist, int c, List *nlist, char *str, char *p)
{
	int i;
	State *s;

	listid++;
	nlist->n = 0;
	for(i=0; i<clist->n; i++){
		s = clist->s[i];
		if(matchchar(s, c))
			addstate(nlist, s->out, str, p + 1);
	}
}

/* Ejecuta el AFND para determinar si coincide con str. */
int
match_nfa(State *start, char *str)
{
	int c;
	List *clist, *nlist, *t;
	char *p;

	clist = startlist(start, &l1, str);
	nlist = &l2;
	for(p=str; *p; p++){
		c = *p & 0xFF;
		step(clist, c, nlist, str, p);
		t = clist; clist = nlist; nlist = t;	/* intercambiar clist, nlist */
	}
	return ismatch(clist);
}

/*
 * Representa un estado AFD: una lista de estados AFND en caché.
 */
typedef struct DState DState;
struct DState
{
	List l;
	DState *next[256];
	DState *left;
	DState *right;
};

static int
listcmp(List *l1, List *l2)
{
	int i;

	if(l1->n < l2->n)
		return -1;
	if(l1->n > l2->n)
		return 1;
	for(i=0; i<l1->n; i++)
		if(l1->s[i] < l2->s[i])
			return -1;
		else if(l1->s[i] > l2->s[i])
			return 1;
	return 0;
}

static int
ptrcmp(const void *a, const void *b)
{
	State *sa = *(State**)a;
	State *sb = *(State**)b;
	if(sa < sb)
		return -1;
	if(sa > sb)
		return 1;
	return 0;
}

DState *alldstates;
DState*
dstate(List *l)
{
	int i;
	DState **dp, *d;

	qsort(l->s, l->n, sizeof l->s[0], ptrcmp);
	dp = &alldstates;
	while((d = *dp) != NULL){
		i = listcmp(l, &d->l);
		if(i < 0)
			dp = &d->left;
		else if(i > 0)
			dp = &d->right;
		else
			return d;
	}
	
	d = malloc(sizeof *d + l->n*sizeof l->s[0]);
	memset(d, 0, sizeof *d);
	d->l.s = (State**)(d+1);
	memmove(d->l.s, l->s, l->n*sizeof l->s[0]);
	d->l.n = l->n;
	*dp = d;
	return d;
}

DState*
startdstate(State *start, char *str)
{
	return dstate(startlist(start, &l1, str));
}

DState*
nextstate(DState *d, int c, char *str, char *p)
{
	step(&d->l, c, &l1, str, p);
	return d->next[c] = dstate(&l1);
}

int
match_dfa(DState *start, char *str)
{
	DState *d, *next;
	int c;
	char *p;
	
	d = start;
	for(p=str; *p; p++){
		c = *p & 0xFF;
		if((next = d->next[c]) == NULL)
			next = nextstate(d, c, str, p);
		d = next;
	}
	return ismatch(&d->l);
}

int
main(int argc, char **argv)
{
	int i;
	State *start;
	int use_dfa = 0;
	int arg_start = 2;
	char *regexp_str = NULL;
	Atom infix[1000];
	Atom post[1000];
	int ninfix, npost;

	if(argc < 3){
		fprintf(stderr, "uso: regex [-n | -d] expr_regular cadena...\n");
		fprintf(stderr, "opciones:\n  -n   usar simulación AFND (por defecto)\n  -d   usar caché AFD\n");
		return 1;
	}

	if(strcmp(argv[1], "-d") == 0) {
		use_dfa = 1;
		if (argc < 4) {
			fprintf(stderr, "uso: regex [-n | -d] expr_regular cadena...\n");
			return 1;
		}
		regexp_str = argv[2];
		arg_start = 3;
	} else if(strcmp(argv[1], "-n") == 0) {
		use_dfa = 0;
		if (argc < 4) {
			fprintf(stderr, "uso: regex [-n | -d] expr_regular cadena...\n");
			return 1;
		}
		regexp_str = argv[2];
		arg_start = 3;
	} else {
		regexp_str = argv[1];
	}
	
	ninfix = tokenize_regex(regexp_str, infix, 1000);
	if(ninfix < 0) {
		fprintf(stderr, "error al parsear la expresión regular: %s\n", regexp_str);
		return 1;
	}

	npost = re2post_atoms(infix, ninfix, post);
	if(npost < 0){
		fprintf(stderr, "bad regexp structure: %s\n", regexp_str);
		return 1;
	}

	/* Verifica si hay aserciones de límites de palabras; vuelve a simulación AFND si las hay */
	int has_boundary = 0;
	for(i=0; i<npost; i++) {
		if(post[i].type == Boundary) {
			has_boundary = 1;
			break;
		}
	}
	if(use_dfa && has_boundary) {
		fprintf(stderr, "aviso: se detectó la aserción de límite \\b; cambiando a simulación AFND\n");
		use_dfa = 0;
	}

	start = post2nfa_atoms(post, npost);
	if(start == NULL){
		fprintf(stderr, "error en la generación del AFND\n");
		return 1;
	}
	
	l1.s = malloc(nstate*sizeof l1.s[0]);
	l2.s = malloc(nstate*sizeof l2.s[0]);

	if (use_dfa) {
		for(i=arg_start; i<argc; i++) {
			DState *dstart_i = startdstate(start, argv[i]);
			if(match_dfa(dstart_i, argv[i]))
				printf("%s\n", argv[i]);
		}
	} else {
		for(i=arg_start; i<argc; i++) {
			if(match_nfa(start, argv[i]))
				printf("%s\n", argv[i]);
		}
	}

	return 0;
}

/*
 * Permission is hereby granted, free of charge, to any person
 * obtaining a copy of this software and associated
 * documentation files (the "Software"), to deal in the
 * Software without restriction, including without limitation
 * the rights to use, copy, modify, merge, publish, distribute,
 * sublicense, and/or sell copies of the Software, and to
 * permit persons to whom the Software is furnished to do so,
 * subject to the following conditions:
 * 
 * The above copyright notice and this permission notice shall
 * be included in all copies or substantial portions of the
 * Software.
 * 
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY
 * KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
 * WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
 * PURPOSE AND NONINFRINGEMENT.  IN NO EVENT SHALL THE AUTHORS
 * OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR
 * OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
 * OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
 * SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
 */

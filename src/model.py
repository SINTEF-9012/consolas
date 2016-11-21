from z3 import *


class ConsolasException(Exception):

    def __init__(self, value):
        self.value = value

    def __str__(self):
        return self.__repr__()

    def __repr__(self):
        return str(self.value)


def _consolas_assert(cond, msg):
    if not cond:
        raise ConsolasException(msg)


# Now begins the definition of predefined Sorts and functions

_Type = DeclareSort('Type')
_Inst = DeclareSort('Inst')

# The 'Default' type and Instance

NilType = Const('NilType', _Type)
nil = Const('nil', _Inst)

super_type = Function('super', _Type, _Type)

actual_type = Function('actual_type', _Inst, _Type)

is_subtype = Function('is_subtype', _Type, _Type, BoolSort())
is_instance = Function('is_instance', _Inst, _Type, BoolSort())
alive = Function('alive', _Inst, BoolSort())
is_abstract = Function('is_abstract', _Type, BoolSort())


# Now begins the definition of models

class ConsolasElement:

    def __init__(self):
        self.z3_element = None

    def z3(self):
        """Convert a Consolas Element to a Z3 expression"""
        return self.z3_element



class Class(ConsolasElement):
    """Typeical class as defined in MOF"""

    def __init__(self, name, supertype=None, abstract=False):
        """
        DockerImage = Class('DockerImage', None, True)
        UbuntuImage = Class('UbuntuImage', DockerImage)

        :param name: Unique class name
        :param supertype: super class
        :param abstract: An abstract class cannot be instantiated
        """
        self.name = name
        self.attributes = {}
        self.references = {}
        self.z3_element = Const(name, _Type)
        self.supertype = supertype
        self.abstract = abstract

    def define_attribute(self, name, type, multiple=False):
        self.attributes[name] = Attribute(name, self, type, multiple, mandatory=True)

    def define_reference(self, name, type, multiple=False, mandatory=False, opposite=None):
        self.references[name] = Reference(name, self, type, multiple, mandatory)
        self.references[name].opposite = opposite

    def get_feature(self, feature):
        if feature in self.attributes:
            return self.attributes[feature]
        elif feature in self.references:
            return self.references[feature]
        else:
            if self.supertype:
                return self.supertype.get_feature(feature)
            else:
                return None

    def all_instances(self):
        var = declare_obj_var(self)
        return SetExpr(PartialExpr(var, And(alive(var.z3()), is_instance(var.z3(), self.z3()))), self)

    def compose_new_class(self, type):
        return CompositeClass(self, type)

    def get_all_feature_names(self):
        result = set()
        t = self
        while t:
            for i in t.attributes:
                result.add(i)
            for i in t.references:
                result.add(i)
            t = t.supertype
        return list(result);

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name

    def forall(self, var, expr):
        return self.all_instances().forall(var, expr)

    def exists(self, var, expr):
        return self.all_instances().exists(var, expr)

    def otherwise(self, var, expr):
        return self.all_instances().exists(var, expr)

    def map(self, var, expr):
        return self.all_instances().map(var, expr)

    def filter(self, var, cond):
        return self.all_instances().filter(var, cond)

    def join(self, other):
        _consolas_assert(isinstance(other, Class), 'a class can only join to another class')
        return self.all_instances().join(other.all_instances())

    def __mul__(self, other):
        return self.join(other)

class CompositeClass(Class):

    def __init__(self, *types):
        self.types = [i for i in types]

    def compose_new_class(self, type):
        lst = list(self.types)
        lst.append(type)
        return CompositeClass(*lst)


class Feature(ConsolasElement):

    def __init__(self, name, parent, type, multiple=False, mandatory=False):
        self.name = name
        self.parent = parent
        self.type = type
        self.multiple = multiple
        self.z3_element = None
        self.mandatory = mandatory

        self._create_z3_element()

    def _create_z3_element(self):
        pass

    def is_reference(self):
        return isinstance(self, Reference)

    def is_attribute(self):
        return isinstance(self, Attribute)


class Attribute(Feature):
    def _create_z3_element(self):
        if self.multiple:
            # Do not support it in the first stage
            self.z3_element = Function(self.name, _Inst, self.type, BoolSort())
        else:
            self.z3_element = Function(self.name, _Inst, self.type)


class Reference(Feature):
    def _create_z3_element(self):
        self.z3_element = self._create_multiple_function() if self.multiple else self._create_single_function()

    def _create_single_function(self):
        function = Function(self.name, _Inst, _Inst)
        return function

    def _create_multiple_function(self):
        function = Function(self.name, _Inst, _Inst, BoolSort())
        return function


class Object(ConsolasElement):

    def __init__(self, name, type, suspended=False):
        self.name = name
        self.type = type
        self.z3_element = Const(name, _Inst)
        self.suspended = suspended
        self.solved_model = None
        self.forced_values = {}

    def force_value(self, feature, value):
        if isinstance(feature, str):
            feature = self.type.get_feature(feature)
        if isinstance(feature, Reference) and isinstance(value, str):
            value = _all_objects[value]
        self.forced_values[feature.name] = value
        return self

    def __str__(self):
        return self.name

    def force_values(self, *values):
        for k, v in values:
            self.force_value(k, v)

    def get_constant(self):
        return ObjectConst(self.name, self.type)

    def cast(self, feature, model):
        feature = self.type.get_feature(feature)
        const = self.get_constant()
        if not feature:
            return None
        if feature.is_attribute():
            result = model.eval(const[feature])
            if is_bool(result):
                return is_true(result)
            if is_int_value(result):
                return int(str(result))
            return None
        elif feature.is_reference() and not feature.multiple:
            for obj in _all_objects.values():
                if str(model.eval(const[feature]==obj.get_constant())) == 'True':
                    return str(obj)
        elif feature.is_reference() and feature.multiple:
            result = []
            for obj in _all_objects.values():
                if str(model.eval(const[feature].contains(obj.get_constant()))) == 'True':
                    result.append(str(obj))
            return result
        return None

    def isinstance_by_decl(self, type_):
        current = self.type
        while current:
            if current == type_:
                return True
            current = current.supertype
        return False

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name

class ConsolasExpr(ConsolasElement):

    def __init__(self):
        self.z3_element = None
        self.type = None

    def __getitem__(self, item):
        raise ConsolasException("GetItem operation not supported. Are you applying it on a Set?")

    def __repr__(self):
        return str(self.z3_element)


class ObjectExpr(ConsolasExpr):

    def __init__(self, z3expr, type):
        self.z3_element = z3expr
        self.type = type

    def __getitem__(self, item):
        if isinstance(item, Feature):
            item = item.name
        _consolas_assert(isinstance(item, str), 'item should be a string')
        _consolas_assert(isinstance(self.type, Class), 'no reference on primitive types')
        _domain = self.type
        feature = _domain.get_feature(item)
        _consolas_assert(feature, '"\%s" is not defined in class "%s"' % (item, _domain))
        z3fun = feature.z3()
        _range = feature.type

        if feature.multiple:
            _consolas_assert(isinstance(_range, Class), "No support of multiple attributes")
            var = declare_obj_var(_range)
            guard = PartialExpr(var, z3fun(self.z3(), var.z3()))
            return SetExpr(guard, _range)
        elif isinstance(feature, Reference):
            return ObjectExpr(z3fun(self.z3()), _range)
        elif isinstance(feature, Attribute):
            return z3fun(self.z3())

    def undefined(self):
        return self.z3() == nil

    def alive(self):
        return alive(self.z3())

    def isinstance(self, clazz):
        _consolas_assert(isinstance(clazz, Class), 'We only check the type of object classes')
        return is_instance(self.z3(), clazz.z3())

    def __eq__(self, other):
        return self.z3() == other.z3()


class ObjectConst(ObjectExpr):

    def __init__(self, name, type):
        self.z3_element = Const(name, _Inst)
        self.type = type


class PartialExpr(ConsolasExpr):

    def __init__(self, var, z3expr):
        self.vars = []
        self.z3_element = z3expr
        if isinstance(var, list):
            self.vars = [(i, None) for i in var]
        else:
            self.vars=[(var, None)]

    def bind(self, index, z3expr):
        self.vars[index] = (self.vars[index][0], z3expr)
        return self

    def bindOne(self, z3expr):
        """Works when there is only one free variable

        :param z3expr: The expression to substitute to the only free variable
        :return:
        """
        _consolas_assert(len(self.vars) == 1, 'Not exactly one free variables')
        return self.bind(0, z3expr)

    def get_one_var(self):
        return self.vars[0][0]

    def complete(self):
        result = self.z3_element
        for i in range(0,len(self.vars)):
            k,v = self.vars[i]
            _consolas_assert(v, 'Free variable "%s" is not bound' % k)
            if isinstance(v, ConsolasExpr):
                self.vars[i] = (k, v.z3())
        #i = self.vars.keys()[0]
        #print (i, self.vars[i])
        #print result

        result = substitute(result, *[(k.z3(), v) for k, v in self.vars])
        return result

    def __str__(self):
        return '(%s | %s)' % ([k for k, v in self.vars], self.z3_element)


# class ObjectVariable(ConsolasExpr):
#
#     def __init__(self, name, type=None):
#         self.name = name
#         self.type = type
#         self.z3_element = Const(name, _Inst)


class SetExpr(ConsolasExpr):
    def __init__(self, guard, type, seed=None):
        self.guard = guard
        self.type = type
        self.seed = seed

    def contains(self, item):
        _consolas_assert(not isinstance(self.guard, list), 'contains only on simple sets. Try check items one by one')
        # if isinstance(item, tuple):
        #     _consolas_assert(len(item) == len(self.guard), 'items has different size with the set')
        #     for i in range(0, len(item)):
        #         if self.seed[i]:
        #             newitem = self.seed[i].bindOne(item[i]).complete()
        #         else:
        #             newitem = item[i]
        #         self.guard[i].bindOne(newitem)
        #     return And([g.complete() for g in self.guard])

        # _consolas_assert(not isinstance(self.guard, list), 'check single item in multi-dimension set')
        if self.seed:
            v = declare_obj_var(self.type)
            return self.exists(v, v == item)
        else:
            return self.guard.bindOne(item).complete()

    def forall(self, var, expr):
        mainvar, guard, body = self._prepare_quantifier(var, expr)
        return ForAll(mainvar, Implies(guard, body))

    def exists(self, var,expr):
        mainvar, guard, body = self._prepare_quantifier(var, expr)
        return Exists(mainvar, And(guard, body))

    def otherwise(self, var, expr):
        mainvar, guard, body = self._prepare_quantifier(var, expr)
        return ForAll(mainvar, Or(guard, body))

    def _prepare_quantifier(self, var, expr):
        if isinstance(expr, ConsolasExpr):
            expr = expr.z3()
        if isinstance(var, list):
            guards = []
            vars = []
            for i in range(0, len(var)):
                v, g, s = (var[i], self.guard[i], self.seed[i])
                if s:
                    expr = PartialExpr(v, expr).bind(i, s).complete()
                    v = s.get_one_var()
                guards.append(g.bindOne(v).complete())
                vars.append(v.z3())
            return vars, And(guards), expr
        else:
            if self.seed:
                body = PartialExpr(var, expr).bindOne(self.seed).complete()
                var = self.seed.get_one_var()
            else:
                body = expr
            guard = self.guard.bindOne(var).complete()
            return var.z3(), guard, body

    def map(self, var, expr):
        _consolas_assert(not isinstance(expr, SetExpr), 'Do not support a set of sets')
        _consolas_assert(not isinstance(var, list),
                         'map only works on simple sets. So please do mapping before joining')
        if isinstance(expr, ConsolasExpr):
            type_ = expr.type
            expr = expr.z3()
        else:
            type_ = None
        seed = PartialExpr(var, expr)
        return SetExpr(self.guard, type_, seed)

    def filter(self, var, cond):
        _consolas_assert(
            not isinstance(var, list),
            'map only works on simple sets. So please do mapping before joining'
        )
        _consolas_assert(is_bool(cond), 'filter condition should be a valid, boolean z3 expression')
        cond1 = PartialExpr(var, cond).bindOne(self.guard.get_one_var()).complete()
        newguard = PartialExpr(self.guard.get_one_var(), And(self.guard.z3_element, cond1))
        return SetExpr(newguard, self.type, self.seed)

    def join(self, other):
        _consolas_assert(not isinstance(other.guard, list), 'Only join a single set')
        new_type = self.type.compose_new_class(other.type)
        if(isinstance(self.guard, list)):
            new_guard = list(self.guard)
        else:
            new_guard = [self.guard]
        new_guard.append(other.guard)
        if isinstance(self.seed, list):
            new_seed = list(self.seed)
        else:
            new_seed = [self.seed]
        new_seed.append(other.seed)

        return SetExpr(new_guard, new_type, new_seed)

    def sum(self):
        _consolas_assert(not isinstance(self.guard, list), 'Sum only works on a simple set')
        _consolas_assert(
            _config_constraints,
            'Sum can be only used after all objects are defined and the object constraints are generated'
        )
        var = self.guard.get_one_var()
        value = self.seed.bindOne(var).complete()
        item = If(self.guard.z3_element, value, 0)
        return Sum([substitute(item, (var.z3(), x.z3()))
                    for x in _all_objects.values()
                    if x.isinstance_by_decl(var.type)])

    def count(self):
        _consolas_assert(not isinstance(self.guard, list), 'Count only works on a simple set')
        _consolas_assert(
            _config_constraints,
            'Count can be only used after all objects are defined and the object constraints are generated'
        )
        var = self.guard.get_one_var()
        item = If(self.guard.z3_element, 1, 0)
        return Sum([substitute(item, (var.z3(), x.z3()))
                    for x in _all_objects.values()
                    if x.isinstance_by_decl(var.type)])

    def __mul__(self, other):
        return self.join(other)

    def __str__(self):
        return '[%s]' % self.guard


_all_classes = {}
_all_objects = {}
_all_vars = {}
_meta_constraints = []
_config_constraints = []


def DefineClass(name, supertype=None, abstract=False):
    _consolas_assert(not (name in _all_classes), 'Class name "%s" is already used' % name)

    class_ = Class(name, supertype, abstract)
    _all_classes[name] = class_
    return class_


def DefineObject(name, type, suspended=False):
    _consolas_assert(not (name in _all_objects), 'Object name "%s" is already used' % name)

    object_ = Object(name, type, suspended)
    _all_objects[name] = object_
    return object_


def get_ancestors(clazz):
    result = []
    supertype = clazz.supertype
    while supertype:
        result.append(supertype)
        supertype = supertype.supertype
    return result


def declare_obj_var(_type, id=None):
    if id:
        _consolas_assert(not (id in _all_vars), 'id "%s" is already used' % id)
    else:
        id = 'var%s%d' % (_type.name, len(_all_vars)+1)
    const = ObjectConst(id, _type)
    _all_vars[id] = const
    return const


def get_declared_var(id):
    return _all_vars[id]


def start_over():
    """
    Clear all the global variables and define classes again. Now only used in unittest...
    :return:
    """
    _all_vars.clear()
    _all_classes.clear()
    _all_objects.clear()
    del _meta_constraints[:]
    del _config_constraints[:]


def meta_fact(constraint):
    _meta_constraints.append(constraint)


def config_fact(constraint):
    _config_constraints.append(constraint)


def generate_meta_constraints():
    del _meta_constraints[:]

    all_class_z3 = [i.z3() for i in _all_classes.values()] + [NilType]
    meta_fact(Distinct(*all_class_z3))

    t1 = Const('t1', _Type)
    t2 = Const('t2', _Type)
    t3 = Const('t3', _Type)
    i1 = Const('i1', _Inst)
    i2 = Const('i2', _Inst)

    meta_fact(ForAll(t1, Or([t1 == i for i in all_class_z3])))
    meta_fact(And([super_type(x.z3())==
                  (x.supertype.z3() if x.supertype else NilType)
                  for x in _all_classes.values()]
                  ))
    meta_fact(ForAll([t1, t2], is_subtype(t1, t2) == Or(super_type(t1)==t2, Exists(t3, And(super_type(t1)==t3, is_subtype(t3, t2))))))
    meta_fact(ForAll([t1, i1], is_instance(i1, t1) == Or(actual_type(i1) == t1, is_subtype(actual_type(i1), t1))))
    meta_fact(ForAll(t1, Implies(is_subtype(NilType, t1), t1 == NilType)))
    meta_fact(ForAll(i1, Or(Not(alive(i1)), Or([actual_type(i1) == x for x in all_class_z3]))))

    meta_fact(And([is_abstract(i.z3()) for i in _all_classes.values() if i.abstract] + [is_abstract(NilType)]))
    meta_fact(ForAll(i1, Implies(alive(i1), Not(is_abstract(actual_type(i1))))))

    meta_fact(And([super_type(NilType) == NilType, actual_type(nil) == NilType, Not(alive(nil))]))

    for class_ in _all_classes.values():
        vdomain = declare_obj_var(class_)
        allinst = class_.all_instances()
        for ref in class_.references.values():
            if ref.multiple:
                vrange = declare_obj_var(ref.type)
                meta_fact(allinst.forall(vdomain, ref.type.all_instances().otherwise(vrange, Not(vdomain[ref].contains(vrange)))))
            else:
                body = And(vdomain[ref].alive(), vdomain[ref].isinstance(ref.type))
                if not ref.mandatory:
                    body = Or(vdomain[ref].undefined(), body)
                meta_fact(allinst.forall(vdomain, body))
                meta_fact(allinst.otherwise(vdomain, vdomain[ref].undefined()))
            if ref.opposite:
                other_ref = ref.type.references[ref.opposite]
                this_side = vdomain[ref] == vrange \
                    if not ref.multiple else \
                    vdomain[ref].contains(vrange)
                other_side = vrange[other_ref] == vdomain \
                    if not other_ref.multiple \
                    else vrange[other_ref].contains(vdomain)
                meta_fact((class_.all_instances() * ref.type.all_instances())
                          .forall([vdomain, vrange], this_side == other_side))

    return _meta_constraints


def generate_config_constraints():

    del _config_constraints[:]

    all_object_z3 = [i.z3() for i in _all_objects.values()] + [nil]
    config_fact(Distinct(*all_object_z3))
    o1 = Const('o1', _Inst)
    config_fact(ForAll(o1, Or([o1 == i for i in all_object_z3])))

    t1 = Const('t1', _Type)

    config_fact(And([obj.get_constant().isinstance(obj.type) for obj in _all_objects.values()]))
    config_fact(And([obj.get_constant().alive() for obj in _all_objects.values() if not obj.suspended]))
    config_fact(ForAll(t1, Or(t1 == NilType, Not(is_instance(nil, t1)))))

    for name, object_ in _all_objects.items():
        oconst = object_.get_constant()
        type_ = object_.type
        for k, v in object_.forced_values.items():
            feature = type_.get_feature(k)
            if not feature.multiple:
                if isinstance(feature, Attribute):
                    config_fact(oconst[feature] == v)
                else:
                    config_fact(oconst[feature] == v.get_constant())
            else:
                _consolas_assert(isinstance(feature, Reference), 'Multiple Attributes not supported yet...')
                config_fact(oconst[feature].contains(v))

    return _config_constraints


def cast_object(object_, model):
    result = {}
    result['name'] = object_.name
    result['alive'] = str(model.eval(alive(object_.z3()))) == 'True'

    result['type'] = None
    for class_ in _all_classes.values():
        if str(model.eval(actual_type(object_.z3()) == class_.z3())) == 'True':
            result['type'] = class_
            break


    for feature in object_.type.get_all_feature_names():
        v = object_.cast(feature, model)
        result[feature] = v

    return result

def cast_all_objects(model):
    result = {}
    for object_ in _all_objects.values():
        v = cast_object(object_, model)
        result[v['name']] = v

    return result



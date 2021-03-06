from src.model import *
from z3 import *

import yaml
import pprint
import inspect
import linecache
import timeit
import itertools
import sys, getopt, os

NSPAR = 2

classes_yaml = """
-
  name: Image
  abstract: True
  reference: [{name: features, type: Feature, multiple: true}]
- 
  name: BuildImage
  supertype: Image
  reference: [
    {name: from, type: Image, mandatory: true},
    {name: using, type: BuildRule, mandatory: true}
  ]
-
  name: DownloadImage
  supertype: Image
-
  name: BuildRule
  reference: [
    {name: requires, type: Feature, multiple: true},
    {name: adds, type: Feature, multiple: true}
  ]
-
  name: Feature
  reference: [
    {name: sup, type: Feature},
    {name: allsup, type: Feature, multiple: true},
    {name: root, type: Feature}
  ]
"""

features = dict()
dimages = dict()
rules = dict()

def prepare_all_sup():
    features = [fea for fea in get_all_objects() if fea.type.name == 'Feature']
    for fea in features:
        sup = fea.forced_values.get('sup', None)
        if sup is None:
            fea.forced_values['allsup'] = []
        else:
            fea.forced_values['allsup'] = [sup]
    # print features
    for f1 in features:
        for f2 in features:
            for f3 in features:
                if (f2 in f1.forced_values['allsup']) and (f3 in f2.forced_values['allsup']):
                    f1.forced_values['allsup'].append(f3)
    #======== See later if we need a root reference or not=========#
    for fea in features:
        roots = [f for f in fea.forced_values['allsup'] if not ('sup' in f.forced_values) ]
        if roots:
            fea.forced_values['root'] = roots[0]
        else:
            fea.forced_values['root'] = fea

    # for fea in features:
    #     print '%s: (%s)' % (fea.name, fea.forced_values['root'])

def afeature(name, sup=None):
    fea = DefineObject(name, Feature)
    if not sup is None:
        fea.force_value('sup', sup)
    features[name] = fea
    return fea

def supersetf(set1, set2):
    return set2.forall(f1, set1.contains(f1))
def subsetf(set1, set2):
    return set1.forall(f1, set2.contains(f1))
def isunionf(res, set1, set2):
    return And(
        res.forall(f1, Or(set1.contains(f1), set2.contains(f1))),
        set1.forall(f1, res.contains(f1)),
        set2.forall(f1, res.contains(f1))
    )

def require_feature(w, f):
    return w.features.exists(f1, Or(f1 == f, f1.allsup.contains(f)))

def require_feature_all(wanted, featurelist):
    return And([require_feature(wanted,f) for f in featurelist])


classes = yaml.load(classes_yaml)

Image, BuildImage, DownloadImage, BuildRule, Feature \
    = load_all_classes(classes)

generate_meta_constraints()

e1, e2 = ObjectVars(Image, 'e1', 'e2')
f1, f2, f3 = ObjectVars(Feature, 'f1', 'f2', 'f3')
wanted = ObjectConst(Image, 'wanted')

buildchains = []
image_spec = None
resultbuildimages = []

def get_wanted(model):
    result = cast_all_objects(model)
    for i in get_all_objects():
        if str(model.eval(wanted == i)) == 'True':
            return result[str(i)]

ampimages = dict()

def print_model_deploy(model):
    result = cast_all_objects(model)
    v = get_wanted(model)
    toprint = '\# %s: ' % v['features']

    chain = []
    bc_item = {
        'chain': chain,
        'features': v['features']
    }
    buildchains.append(bc_item)
    newkey = ''
    newname = None
    newtag = None
    newfeatures = v['features']
    dep = []
    while True:
        if 'using' in v:
            if newname is None:
                newname = v['using']
            else:
                if newtag is None:
                    newtag = v['using']
                else:
                    newtag = newtag + '-' + v['using']
            newkey = newkey + v['using']
            for x in image_spec['buildingrules'][v['using']].get('depends', []):
                dep.append(x)
            toprint = toprint + '%s(%s) -> '%(v['name'], v['using'])
            chain.append({'rule': v['using']})
            v = result[v['from']]
        else:
            toprint = toprint + v['name']
            dimage = image_spec['downloadimages'][v['name']]
            chain.append({'name': dimage['name'], 'tag': dimage['tag']})
            newtag = '%s-%s-%s' % (newtag, dimage['name'], dimage['tag'])
            newkey = newkey + v['name']
            break
    ampimages[newkey] = {
        'name': newname.lower(),
        'tag': newtag.lower(),
        'features': newfeatures,
        'dep': dep
    }
    print toprint

covered = []

def find_covered_features(model):
    v = get_wanted(model)
    for f in v['features']:
        for i in get_all_objects():
            if i.name == f and not (i in covered):
                covered.append(i)
    print 'features covered: %s' % covered


def declare_feature(spec, parent):
    if type(spec) is list:
        for str in spec:
            afeature(str, parent)
    if type(spec) is dict:
        for str, val in spec.iteritems():
            newparent = afeature(str, parent)
            declare_feature(val, newparent)

def resolve_features(featurenames):
    return [features[n] for n in featurenames]

def generate(workingdir):
    global image_spec

    with open(workingdir+'/features.yml', 'r') as stream:
        feature_spec = yaml.load(stream)
    declare_feature(feature_spec, None)
    # print features
    prepare_all_sup()

    print "Start search for images"

    with open(workingdir + '/images.yml', 'r') as stream:
        image_spec = yaml.load(stream)
    for name, value in image_spec['downloadimages'].iteritems():
        img = DefineObject(name, DownloadImage)
        dimages[name] = img
        img.force_value('features', resolve_features(value['features']))

    for name, value in image_spec['buildingrules'].iteritems():
        img = DefineObject(name, BuildRule)
        rules[name] = img
        img.force_value('requires', resolve_features(value['requires']))
        img.force_value('adds', resolve_features(value['adds']))


    images = [DefineObject('image%d'%i, BuildImage, suspended=True) for i in range(0, NSPAR)]

    # wanted = ObjectConst(Image, 'wanted')

    generate_config_constraints()

    bi1 = ObjectVar(BuildImage, 'bi1')
    bi2 = ObjectVar(BuildImage, 'bi2')
    meta_facts(
        BuildImage.forall(bi1, And(
            bi1.using.requires.forall(
                f1, bi1['from'].features.exists(
                    f2, Or(f2==f1, f2.allsup.contains(f1))
                )
            ),
            isunionf(bi1.features, bi1['from'].features, bi1.using.adds)
        )),
        BuildImage.forall(bi1, Not(bi1['from'] == bi1)),
        BuildImage.forall(bi1, bi1.features.exists(f1, Not(bi1['from'].features.contains(f1)))),
        # Image.forall(e1, (e1.features * e1.features).forall(
        #     [f1, f2], Or(f1==f2, Not(Feature.exists(f3, And(f1.allsup.contains(f3), f2.allsup.contains(f3)))))
        # )),
        Image.forall(e1, (e1.features * e1.features).forall(
            [f1, f2], Or(f1 == f2, Not(f1.root == f2.root))
        ))
    )

    solver = Optimize()
    solver.add(*get_all_meta_facts())
    solver.add(*get_all_config_facts())

    solver.add(wanted.isinstance(Image))
    solver.add(wanted.alive())

    solver.add(require_feature_all(wanted, [features[x] for x in image_spec['mandatoryfeature']]))

    for cst in image_spec['constraints']:
        solver.add(eval(cst))

    for i in range(0, 4):
        print 'Image number %d in %.2f seconds.>>' % (i, timeit.timeit(solver.check, number=1))
        print_model_deploy(solver.model())
        find_covered_features(solver.model())
        solver.maximize(wanted.features.filter(f1, And([Not(f1 == fea) for fea in covered])).count())
        print ''
    with open(workingdir + '/out/genimages.yml', 'w') as stream:
        yaml.dump({'buildchains': buildchains}, stream)
        stream.close()

    with open(workingdir + '/out/ampimages.yml', 'w') as stream:
        yaml.dump({'images': ampimages}, stream)
        stream.close()

HELPTEXT = 'dockerbuild.py -d <working dir>'
def main(argv):
    workingdir = ''
    try:
        opts, args = getopt.getopt(argv,"hd:",["dir="])
    except getopt.GetoptError:
        print HELPTEXT
        sys.exit(2)
    for opt, arg in opts:
        if opt == '-h':
            print HELPTEXT
            sys.exit()
        elif opt in ("-d", "--dir"):
            workingdir = arg

    print 'Working directory is ', workingdir

    if workingdir == '':
        print 'working directory required: ' + HELPTEXT
        exit()

    generate(workingdir)


if __name__ == "__main__":
    main(sys.argv[1:])
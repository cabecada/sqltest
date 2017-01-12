# -*- coding: utf-8 -*-

import glob
import yaml
import os.path
import time
import bnf
import sys
import sqlite3
import cgi
from jinja2 import Template

def get_all_features(standard):
    features_file = open("standards/%s/features.yml" % standard, "r")
    all_features = yaml.load(features_file)

    for group in ('mandatory', 'optional'):
        for feature_id in all_features[group]:
            all_features[group][feature_id] = {
                'description': all_features[group][feature_id]
            }

    return all_features

def feature_id_from_file_path(file_path):
    return file_path.split('/')[-1][:-4]

def output_file(feature_file_path):
    return feature_file_path[:-4] + ".tests.yml"

def all_features_with_tests(standard):
    all_files = glob.glob("standards/%s/*.yml" % standard)
    feature_files = []
    for feature_file_path in sorted(all_files):
        basename = os.path.basename(feature_file_path)
        if basename[0].upper() != basename[0] or '.tests.yml' in basename:
            continue

        feature_files.append(feature_file_path)

    return feature_files

def get_rules(standard):
    raw_rules = bnf.parse_bnf_file('standards/%s/bnf.txt' % standard)
    return bnf.analyze_rules(raw_rules)

def generate_tests(feature_file_path):
    feature_file = open(feature_file_path, "r")
    tests = yaml.load_all(feature_file)
    basename = os.path.basename(feature_file_path)
    result_tests = []
    test_number = 0

    for test in tests:
        test_number += 1

        override = {}
        if 'override' in test:
            override = test['override']
        for name in override:
            override[name] = bnf.ASTKeyword(str(override[name]))

        exclude = []
        if 'exclude' in test:
            exclude = test['exclude']

        print(test['sql'])
        sqls = bnf.get_paths_for_rule(rules, test['sql'], override, exclude)

        for rule_number in xrange(0, len(sqls)):
            test_id = '%s_%02d_%02d' % (
                basename.split('.')[0].replace('-', '_').lower(),
                test_number, rule_number + 1
            )

            result_tests.append({
                'id': test_id,
                'feature': basename[:-4],
                'sql': sqls[rule_number].replace('TN', test_id)
            })

    with open(output_file(feature_file_path), "w") as f:
        f.write(yaml.dump_all(result_tests, default_flow_style=False))

standard = '2016'
rules = get_rules(standard)
feature_file_paths = all_features_with_tests(standard)
test_files = {}

for feature_file_path in feature_file_paths:
    feature_id = feature_id_from_file_path(feature_file_path)
    generated_file_path = output_file(feature_file_path)
    test_files[feature_id] = {
        'path': generated_file_path
    }

    #if os.path.isfile(generated_file_path):
    #    continue

    print("Generating tests for %s" % feature_id)
    generate_tests(feature_file_path)

# Prepare the database
db_file = 'test.db'
if os.path.isfile(db_file):
    os.remove(db_file)
conn = sqlite3.connect(db_file)
c = conn.cursor()

# Run the tests
for feature_id in sorted(test_files):
    file_path = test_files[feature_id]['path']
    test_file = open(file_path, "r")
    tests = list(yaml.load_all(test_file))

    test_files[feature_id]['pass'] = 0
    test_files[feature_id]['fail'] = 0

    print('\n%s: %s tests' % (feature_id, len(tests)))

    for test in tests:
        did_pass = True
        try:
            c.execute(test['sql'])
        except sqlite3.OperationalError:
            did_pass = False

        if did_pass:
            test_files[feature_id]['pass'] += 1
            print('  ✓ %s' % test['sql'])
        else:
            test_files[feature_id]['fail'] += 1
            print('  ✗ %s' % test['sql'])

#conn.commit()
conn.close()

# Merge the rules with the original features
all_features = get_all_features(standard)
for feature_id in test_files:
    all_features['mandatory'][feature_id].update(test_files[feature_id])

def get_html_color_for_pass_rate(pass_rate):
    # The returned weighted gradient goes from red at 0% to yellow at 75% to
    # green at 100%. It is weighted because what feels like a "pass" where it
    # start transitioning to green should really start at 75% rather than 50%.
    if pass_rate <= 0.75:
        r, g, b = (255, 255 * pass_rate * 1.333, 0)
    else:
        r, g, b = (255 - (255 * (pass_rate - 0.75) * 4), 255, 0)
    
    return '#%x%x%x' % (r, g, b)

# Generate HTML report

with open("templates/report.html", "r") as report_template:
    t = Template(report_template.read())

    feats = {
        'mandatory': [],
        'optional': []
    }

    total_tests = 0
    total_passed = 0
    
    for category in ('mandatory', 'optional'):
        for feature_id in sorted(all_features[category]):
            f = all_features[category][feature_id]

            percent = '&nbsp;'
            color = 'grey'
            if 'pass' in f:
                pass_rate = float(f['pass']) / (float(f['pass']) + float(f['fail']))
                percent = '%.0d%% (%d/%d)' % (pass_rate * 100, f['pass'], int(f['pass']) + int(f['fail']))
                color = get_html_color_for_pass_rate(pass_rate)
                total_tests += f['pass'] + f['fail']
                total_passed += f['pass']

            feats[category].append({
                'id': feature_id,
                'description': cgi.escape(all_features[category][feature_id]['description']),
                'color': color,
                'percent': percent,
            })

    with open("report.html", "w") as report_file:
        report_file.write(t.render(features=feats, len=len, total_tests=total_tests, total_passed=total_passed))

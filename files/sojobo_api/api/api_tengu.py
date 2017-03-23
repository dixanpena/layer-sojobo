# !/usr/bin/env python3
# Copyright (C) 2017  Qrama
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
# pylint: disable=c0111,c0301,c0325,w0406,e0401
import os
import shutil
from flask import send_file, request, Blueprint
from sojobo_api.api import w_errors as errors, w_juju as juju
from sojobo_api.api.w_juju import execute_task, execute_task_con

TENGU = Blueprint('tengu', __name__)


def get():
    return TENGU


@TENGU.route('/login', methods=['POST'])
def login():
    try:
        execute_task(juju.authenticate, request.headers['api-key'], request.authorization)
        code, response = 200, 'Success'
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@TENGU.route('/controllers', methods=['GET'])
def get_all_info():
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization)
        code, response = 200, execute_task(juju.get_controllers_info, token)
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@TENGU.route('/controllers', methods=['POST'])
def create_controller():
    if request.json is None:
        data = request.form
    else:
        data = request.json
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization)
        controller = juju.check_input(data['controller'])
        c_type = execute_task(juju.check_c_type, data['type'])
        if token.is_admin:
            if execute_task(juju.controller_exists, controller):
                code, response = errors.already_exists('controller')
            elif 'file' in request.files:
                path = '{}/files/credentials/google-{}.json'.format(juju.get_api_dir(), controller)
                request.files['file'].save(path)
                execute_task(juju.create_controller, c_type, controller, data['region'], path)
                code, response = 200, execute_task(juju.get_controller_info, token.set_controller(data['controller']))
            else:
                execute_task(juju.create_controller, c_type, controller, data['region'], data['credentials'])
                code, response = 200, execute_task(juju.get_controller_info, token.set_controller(controller))
        else:
            code, response = errors.no_permission()
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@TENGU.route('/controllers/<controller>', methods=['GET'])
def get_controller_info(controller):
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization, juju.check_input(controller))
        code, response = 200, execute_task(juju.get_controller_info, token)
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@TENGU.route('/controllers/<controller>', methods=['DELETE'])
def delete_controller(controller):
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization, juju.check_input(controller))
        if token.c_access == 'superuser':
            execute_task(juju.delete_controller, token)
            code, response = 200, execute_task(juju.get_controllers_info, token)
        else:
            code, response = errors.no_permission()
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@TENGU.route('/controllers/<controller>/models', methods=['POST'])
def create_model(controller):
    data = request.json
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization, juju.check_input(controller))
        model = juju.check_input(data['model'])
        if execute_task_con(juju.model_exists, token, model):
            code, response = errors.already_exists('model')
        elif token.c_access == 'add-model' or token.c_access == 'superuser':
            execute_task_con(juju.create_model, token, model, data.get('ssh-key', None))
            code, response = 200, execute_task_con(juju.get_model_info, token.set_model(model))
        else:
            code, response = errors.no_permission()
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@TENGU.route('/controllers/<controller>/models', methods=['GET'])
def get_models_info(controller):
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization, juju.check_input(controller))
        code, response = 200, execute_task_con(juju.get_models_info, token)
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@TENGU.route('/controllers/<controller>/models/<model>', methods=['GET'])
def get_model_info(controller, model):
    try:
        token = juju.authenticate(request.headers['api-key'], request.authorization,
                                  juju.check_input(controller), juju.check_input(model))
        code, response = 200, juju.get_model_info(token)
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@TENGU.route('/controllers/<controller>/models/<model>', methods=['POST'])
def add_bundle(controller, model):
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization,
                             juju.check_input(controller), juju.check_input(model))
        if token.m_access == 'admin' or token.m_access == 'write':
            execute_task(juju.deploy_app, token, request.json['bundle'])
            code, response = 200, execute_task(juju.get_model_info, token)
        else:
            code, response = errors.no_permission()
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@TENGU.route('/controllers/<controller>/models/<model>', methods=['DELETE'])
def delete_model(controller, model):
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization,
                             juju.check_input(controller), juju.check_input(model))
        if token.m_access == 'admin':
            execute_task(juju.delete_model, token)
            code, response = 200, execute_task(juju.get_models_info, token)
        else:
            code, response = errors.no_permission()
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@TENGU.route('/controllers/<controller>/models/<model>/sshkey', methods=['GET'])
def get_ssh_keys(controller, model):
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization,
                             juju.check_input(controller), juju.check_input(model))
        if token.m_access == 'admin':
            code, response = 200, execute_task(juju.get_ssh_keys, token)
        else:
            code, response = errors.no_permission()
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@TENGU.route('/controllers/<controller>/models/<model>/sshkey', methods=['POST'])
def add_ssh_key(controller, model):
    data = request.json
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization,
                             juju.check_input(controller), juju.check_input(model))
        if token.m_access == 'admin':
            execute_task(juju.add_ssh_key, token, data['ssh-key'])
            code, response = 200, execute_task(juju.get_ssh_keys, token)
        else:
            code, response = errors.no_permission()
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@TENGU.route('/controllers/<controller>/models/<model>/sshkey', methods=['DELETE'])
def remove_ssh_key(controller, model):
    data = request.json
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization,
                             juju.check_input(controller), juju.check_input(model))
        if token.m_access == 'admin':
            execute_task(juju.remove_ssh_key, token, data['ssh-key'])
            code, response = 200, execute_task(juju.get_ssh_keys, token)
        else:
            code, response = errors.no_permission()
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@TENGU.route('/controllers/<controller>/models/<model>/applications', methods=['GET'])
def get_applications_info(controller, model):
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization,
                             juju.check_input(controller), juju.check(model))
        if token.m_access is not None:
            code, response = 200, execute_task(juju.get_applications_info, token)
        else:
            code, response = errors.no_permission()
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@TENGU.route('/controllers/<controller>/models/<model>/applications', methods=['POST'])
def add_application(controller, model):
    data = request.json
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization,
                             juju.check_input(controller), juju.check_input(model))
        if execute_task(juju.app_exists, token, data['application']):
            code, response = errors.already_exists('application')
        else:
            if token.m_access == 'write' or token.m_access == 'admin':
                series = juju.check_input(data.get('series', None))
                machine = juju.check_input(data.get('target', None))
                app = juju.check_input(data['application'])
                if series in execute_task(juju.get_application_info, token, app)['series'] and execute_task(juju.cloud_supports_series, token, series) and execute_task(juju.machine_matches_series, token, machine, series):
                    execute_task(juju.deploy_app, token, app, series, machine)
                    code, response = 200, juju.get_application_info(token, app)
                elif series in execute_task(juju.get_application_info, token, app)['series'] and execute_task(juju.cloud_supports_series, token, series):
                    code, response = 400, 'Target machine and application series mismatch'
                elif execute_task(juju.cloud_supports_series, token, series) and execute_task(juju.machine_matches_series, token, machine, series):
                    code, response = 400, 'The application does not support this series'
                else:
                    code, response = 400, 'The cloud does not support this series, nor does the application'
            else:
                code, response = errors.no_permission()
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@TENGU.route('/controllers/<controller>/models/<model>/applications/<application>', methods=['GET'])
def get_application_info(controller, model, application):
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization,
                             juju.check_input(controller), juju.check_input(model))
        app = juju.check_input(application)
        if execute_task(juju.app_exists, token, app):
            code, response = 200, execute_task(juju.get_application_info, token, app)
        else:
            code, response = errors.does_not_exist('application')
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@TENGU.route('/controllers/<controller>/models/<model>/applications/<application>', methods=['DELETE'])
def remove_app(controller, model, application):
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization,
                             juju.check_input(controller), juju.check_input(model))
        app = juju.check_input(application)
        if execute_task(juju.app_exists, token, app):
            if token.m_access == 'write' or token.m_access == 'admin':
                execute_task(juju.remove_app, token, app)
                code, response = 200, execute_task(juju.get_applications_info, token)
            else:
                code, response = errors.no_permission()
        else:
            code, response = errors.does_not_exist('application')
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@TENGU.route('/controllers/<controller>/models/<model>/machines/', methods=['GET'])
def get_machines_info(controller, model):
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization,
                             juju.check_input(controller), juju.check_input(model))
        code, response = 200, execute_task(juju.get_machines_info, token)
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@TENGU.route('/controllers/<controller>/models/<model>/machines/<machine>', methods=['GET'])
def get_machine_info(controller, model, machine):
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization,
                             juju.check_input(controller), juju.check_input(model))
        mach = juju.check_input(machine)
        if execute_task(juju.machine_exists, token, mach):
            code, response = 200, execute_task(juju.get_machine_info, token, mach)
        else:
            code, response = errors.does_not_exist('machine')
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@TENGU.route('/controllers/<controller>/models/<model>/machines', methods=['POST'])
def add_machine(controller, model):
    data = request.json
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization,
                             juju.check_input(controller), juju.check_input(model))
        if token.m_access == 'write' or token.m_access == 'admin':
            series = juju.check_input(data.get('series', None))
            if execute_task(juju.cloud_supports_series, token, series):
                execute_task(juju.add_machine, token, series)
                code, response = 200, execute_task(juju.get_machines_info, token)
            else:
                code, response = 400, 'This cloud does not support this version of Ubuntu'
        else:
            code, response = errors.no_permission()
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@TENGU.route('/controllers/<controller>/models/<model>/machines/<machine>', methods=['DELETE'])
def remove_machine(controller, model, machine):
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization,
                             juju.check_input(controller), juju.check_input(model))
        mach = juju.check_input(machine)
        if execute_task(juju.machine_exists, token, mach):
            if token.m_access == 'write' or token.m_access == 'admin':
                execute_task(juju.remove_machine, token, mach)
                code, response = 200, execute_task(juju.get_machines_info, token)
            else:
                code, response = errors.no_permission()
        else:
            code, response = errors.does_not_exist('machine')
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@TENGU.route('/controllers/<controller>/models/<model>/applications/<application>/units', methods=['GET'])
def get_units_info(controller, model, application):
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization,
                             juju.check_input(controller), juju.check_input(model))
        app = juju.check_input(application)
        if execute_task(juju.app_exists, token, app):
            code, response = 200, execute_task(juju.get_units_info, token, app)
        else:
            code, response = errors.does_not_exist('application')
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@TENGU.route('/controllers/<controller>/models/<model>/applications/<application>/units', methods=['POST'])
def add_unit(controller, model, application):
    data = request.json
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization,
                             juju.check_input(controller), juju.check_input(model))
        app = juju.check_input(application)
        if execute_task(juju.app_exists, token, app):
            if token.m_access == 'write' or token.m_access == 'admin':
                execute_task(juju.add_unit, token, application, data.get('target', None))
                code, response = 200, execute_task(juju.get_units_info, token, app)
            else:
                code, response = errors.no_permission()
        else:
            code, response = errors.does_not_exist('application')
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@TENGU.route('/controllers/<controller>/models/<model>/applications/<application>/units/<unitnumber>', methods=['DELETE'])
def remove_unit(controller, model, application, unitnumber):
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization,
                             juju.check_input(controller), juju.check_input(model))
        app = juju.check_input(application)
        unum = juju.check_input(unitnumber)
        if execute_task(juju.get_unit_info, token, app, unum) is not {}:
            if token.m_access == 'write' or token.m_access == 'admin':
                execute_task(juju.remove_unit, token, app, unum)
                code, response = 200, execute_task(juju.get_units_info, token, app)
            else:
                code, response = errors.no_permission()
        else:
            code, response = errors.does_not_exist('unit')
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@TENGU.route('/controllers/<controller>/models/<model>/applications/<application>/units/<unitnumber>', methods=['GET'])
def get_unit_info(controller, model, application, unitnumber):
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization,
                             juju.check_input(controller), juju.check_input(model))
        app = juju.check_input(application)
        unum = juju.check_input(unitnumber)
        if execute_task(juju.get_unit_info, token, app, unum) is not {}:
            code, response = 200, execute_task(juju.get_unit_info, token, app, unum)
        else:
            code, response = errors.does_not_exist('unit')
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@TENGU.route('/controllers/<controller>/models/<model>/relations', methods=['GET'])
def get_relations_info(controller, model):
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization,
                             juju.check_input(controller), juju.check_input(model))
        code, response = 200, execute_task(juju.get_relations_info, token)
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@TENGU.route('/controllers/<controller>/models/<model>/relations', methods=['PUT'])
def add_relation(controller, model):
    data = request.json
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization,
                             juju.check_input(controller), juju.check_input(model))
        app1, app2 = juju.check_input(data['app1']), juju.check_input(data['app2'])
        if execute_task(juju.app_exists, token, app1) and execute_task(juju.app_exists, token, app2):
            if token.m_access == 'write' or token.m_access == 'admin':
                execute_task(juju.add_relation, token, app1, app2)
                code, response = 200, execute_task(juju.get_relations_info, token)
            else:
                code, response = errors.no_permission()
        else:
            code, response = errors.does_not_exist('application')
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@TENGU.route('/controllers/<controller>/models/<model>/relations/<application>', methods=['GET'])
def get_relations(controller, model, application):
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization,
                             juju.check_input(controller), juju.check_input(model))
        app = juju.check_input(application)
        if execute_task(juju.app_exists, token, app):
            code, response = 200, execute_task(juju.get_application_info, token, app)['relations']
        else:
            code, response = errors.does_not_exist('application')
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@TENGU.route('/controllers/<controller>/models/<model>/relations/<app1>/<app2>', methods=['DELETE'])
def remove_relation(controller, model, app1, app2):
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization,
                             juju.check_input(controller), juju.check_input(model))
        appl1, appl2 = juju.check_input(app1), juju.check_input(app2)
        if execute_task(juju.app_exists, token, appl1) and execute_task(juju.app_exists, token, appl2):
            if token.m_access == 'write' or token.m_access == 'admin':
                execute_task(juju.remove_relation, token, appl1, appl2)
                code, response = 200, execute_task(juju.get_relations_info, token)
            else:
                code, response = errors.no_permission()
        else:
            code, response = errors.no_app()
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@TENGU.route('/backup', methods=['GET'])
def backup_controllers():
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization)
        if token.is_admin:
            apidir = juju.get_api_dir()
            homedir = '/home/{}/.local/share/juju'.format(juju.get_api_user())
            # shutil.copy2('{}/install_credentials.py'.format(apidir), '{}/backup/install_credentials.py'.format(apidir))
            try:
                shutil.copy2('{}/clouds.yaml'.format(homedir), '{}/backup/clouds.yaml'.format(apidir))
            except FileNotFoundError:
                pass
            try:
                shutil.copytree('{}/files/credentials'.format(apidir), '{}/backup/credentials'.format(apidir))
            except FileExistsError:
                os.rmdir('{}/backup/credentials'.format(apidir))
                shutil.copytree('{}/files/credentials'.format(apidir), '{}/backup/credentials'.format(apidir))
            except FileNotFoundError:
                pass
            shutil.copy2('{}/credentials.yaml'.format(homedir), '{}/backup/credentials.yaml'.format(apidir))
            shutil.copy2('{}/controllers.yaml'.format(homedir), '{}/backup/controllers.yaml'.format(apidir))
            shutil.make_archive('{}/backup'.format(apidir), 'zip', '{}/backup/'.format(apidir))
            return send_file('{}/backup.zip'.format(apidir))
        else:
            code, response = errors.no_permission()
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)

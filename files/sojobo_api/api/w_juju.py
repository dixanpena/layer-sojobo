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
# pylint: disable=c0111,c0301,c0325,c0103,r0204,r0913,r0902,e0401,C0302
from importlib import import_module
import json
import os
from subprocess import check_output, STDOUT, CalledProcessError
import asyncio
import yaml
from flask import abort, Response
from sojobo_api.api import w_errors as errors, w_mongo as mongo
from sojobo_api import settings
from git import Repo
from juju.model import Model
from juju.controller import Controller
from juju.cloud import Cloud
from juju.errors import JujuAPIError
#from juju.client import client
from datetime import datetime
from juju.client.connection import JujuData
################################################################################
# TENGU FUNCTIONS
################################################################################
class JuJu_Token(object):#pylint: disable=R0903
    def __init__(self, auth):
        self.username = auth.username
        self.password = auth.password
        self.is_admin = self.set_admin()

    def set_admin(self):
        return self.username == settings.JUJU_ADMIN_USER and self.password == settings.JUJU_ADMIN_PASSWORD


class Model_Connection(object):
    def __init__(self):
        self.m_name = None
        self.m_access = None
        self.m_uuid = None
        self.m_connection = None


    def m_shared_name(self):
        return "{}/{}".format(settings.JUJU_ADMIN_USER, self.m_name)


    async def set_model(self, token, controller, modelname):
        self.m_name = modelname
        if self.m_connection is not None:
            await self.m_connection.disconnect()
        self.m_uuid = await get_model_uuid(controller, self)
        self.m_connection = await connect_model(controller, self, token)
        self.m_access = await get_model_access(self, controller, token.username)
        return self


    async def disconnect(self):
        if self.m_connection is not None:
            await self.m_connection.disconnect()

class Controller_Connection(object):
    def __init__(self):
        self.url = None
        self.c_name = None
        self.c_access = None
        self.c_token = None
        self.c_connection = None


    async def set_controller(self, token, c_name):
        controllers = await get_all_controllers()
        c_type, c_endpoint = controllers[c_name]['cloud'], controllers[c_name]['api-endpoints'][0]
        self.url = c_endpoint
        self.c_name = c_name
        self.c_token = getattr(get_controller_types()[c_type], 'Token')(c_endpoint, token.username, token.password)
        if self.c_connection is not None:
            await self.c_connection.disconnect()
        self.c_connection = await connect_controller(self, token)
        self.c_access = await get_controller_access(self, token.username)
        return self

    async def disconnect(self):
        if self.c_connection is not None:
            await self.c_connection.disconnect()


def get_api_key():
    with open('{}/api-key'.format(get_api_dir()), 'r') as key:
        apikey = key.readlines()[0]
    return apikey


def get_api_dir():
    return settings.SOJOBO_API_DIR


def get_api_user():
    return settings.SOJOBO_USER


def get_controller_types():
    c_list = {}
    for f_path in os.listdir('{}/controllers'.format(settings.SOJOBO_API_DIR)):
        if 'controller_' in f_path and '.pyc' not in f_path:
            name = f_path.split('.')[0]
            c_list[name.split('_')[1]] = import_module('sojobo_api.controllers.{}'.format(name))
    return c_list

def execute_task(command, *args):
    loop = asyncio.get_event_loop()
    loop.set_debug(False)
    result = loop.run_until_complete(command(*args))
    return result


def create_response(http_code, return_object):
    return Response(
        json.dumps(return_object),
        status=http_code,
        mimetype='application/json',
    )


def output_pass(commands, controller=None, model=None):
    if controller is not None and model is not None:
        commands.extend(['-m', '{}:{}'.format(controller, model)])
    elif controller is not None:
        commands.extend(['-c', controller])
    try:
        result = check_output(commands, input=bytes('{}\n'.format(settings.JUJU_ADMIN_PASSWORD), 'utf-8'), stderr=STDOUT).decode('utf-8')
        if 'please enter password' in result:
            result = result.split('\n', 1)[1]
    except CalledProcessError as e:
        msg = e.output.decode('utf-8')
        if 'no credentials provided' in msg:
            check_output(['juju', 'login', settings.JUJU_ADMIN_USER, '-c', controller], input=bytes('{}\n'.format(settings.JUJU_ADMIN_PASSWORD), 'utf-8'))
            result = output_pass(commands)
        else:
            error = errors.cmd_error(msg)
            abort(error[0], error[1])
    return result


def check_input(data):
    if data is not None:
        items = data.split(':', 1)
        if len(items) > 1 and items[0].lower() not in ['local', 'github', 'lxd', 'kvm']:
            error = errors.invalid_option(items[0])
            abort(error[0], error[1])
        else:
            for item in items:
                if not all(x.isalpha() or x.isdigit() or x == '-' for x in item):
                    error = errors.invalid_input()
                    abort(error[0], error[1])
            result = data.lower()
    else:
        result = None
    return result


# def check_access(access):
#     acc = access.lower()
#     if c_access_exists(acc) or m_access_exists(acc):
#         return acc
#     else:
#         error = errors.invalid_access('access')
#         abort(error[0], error[1])


async def connect_controller(con, token): #pylint: disable=e0001
    controller = Controller()
    await controller.connect(
        con.url,
        token.username,
        token.password,
        None,)
    return controller


async def connect_model(con, mod, token): #pylint: disable=e0001
    model = Model()
    await model.connect(
        con.url,
        mod.m_uuid,
        token.username,
        token.password,
        None, )
    return model


async def check_login(token):
    if token.username == settings.JUJU_ADMIN_USER:
        return token.password == settings.JUJU_ADMIN_PASSWORD
    else:
        controller = Controller_Connection()
        try:
            cont_name = list(await get_all_controllers())[0]
            await controller.set_controller(token, cont_name)
            return True
        except JujuAPIError:
            return False
        finally:
            controller.disconnect()


async def authenticate(api_key, auth, controller=None, modelname=None):
    token = JuJu_Token(auth)
    if controller is None and api_key != get_api_key() or not await check_login(token):
        error = errors.unauthorized()
        abort(error[0], error[1])
    elif controller is not None and await controller_exists(controller):
        cont_con = Controller_Connection()
        await cont_con.set_controller(token, controller)
        modelex = await model_exists(cont_con, modelname)
        if cont_con.c_access is None:
            error = errors.no_access('controller')
            abort(error[0], error[1])
        if modelname is not None and modelex:
            mod_con = Model_Connection()
            await mod_con.set_model(token, cont_con, modelname)
            if mod_con.m_access is None:
                error = errors.no_access('model')
                abort(error[0], error[1])
        elif modelname is not None and not modelex:
            error = errors.does_not_exist('model')
            abort(error[0], error[1])
    elif not await controller_exists(controller) and controller is not None:
        error = errors.does_not_exist('controller')
        abort(error[0], error[1])
    if controller and modelname:
        return token, cont_con, mod_con
    elif controller:
        return token, cont_con
    else:
        return token
###############################################################################
# CONTROLLER FUNCTIONS
###############################################################################
async def cloud_supports_series(controller_connection, series):
    if series is None:
        return True
    else:
        return series in get_controller_types()[controller_connection.c_token.type].get_supported_series()


async def check_c_type(c_type):
    if check_input(c_type) in get_controller_types().keys():
        return c_type.lower()
    else:
        error = errors.invalid_controller(c_type)
        abort(error[0], error[1])


# libjuju: nok (TODO change user password wel, eerst aanpassingen aan subordinates)
async def create_controller(c_type, name, region, credentials):
    get_controller_types()[c_type].create_controller(name, region, credentials)
    pswd = os.environ.get('JUJU_ADMIN_PASSWORD')
    # try:
    #     con = Controller_Connection()
    #     controller = Controller()
    #     # await controller.connect(
    #     #     con[1],
    #     #     'admin',
    #     #     '',
    #     #     None,)
    #     await controller.change_user_password('admin', pswd)
    # except NotImplementedError:
    check_output(['juju', 'change-user-password', 'admin', '-c', name], input=bytes('{}\n{}\n'.format(pswd, pswd), 'utf-8'))

    controller = Controller_Connection()
    return controller


async def delete_controller(con):
    try:
        controller = con.c_connection
        await controller.destroy(True)
        cloud = Cloud()
        await cloud.remove_credential(con.c_name)
    except NotImplementedError:
        output_pass(['juju', 'destroy-controller', '-y'], con.c_name)
        output_pass(['juju', 'remove-credential', con.c_token.type, con.c_name])


async def get_all_controllers():
    try:
        jujudata = JujuData()
        result = jujudata.controllers()
    except FileNotFoundError:
        result = []
    return result


async def controller_exists(c_name):
    return c_name in list(await get_all_controllers())


async def get_controller_access(con, username):
    try:
        controller = con.c_connection
        user = await controller.get_user(username, True)
        result = user.serialize()['results'][0].serialize()['result'].serialize()['access']
    except NotImplementedError:
        users = json.loads(output_pass(['juju', 'users', '--format', 'json'], con.c_name))
        result = None
        for user in users:
            if user['user-name'] == username:
                access = user['access']
                if await c_access_exists(access):
                    result = access
    except json.decoder.JSONDecodeError as e:
        error = errors.cmd_error(e)
        abort(error[0], error[1])
    return result


async def get_controllers_info():
#     result = await get_all_controllers()
#     output = []
#     for m in result:
#         cont_con = Controller_Connection()
#         cont = await cont_con.set_controller(token, m)
#         if cont.c_access is not None:
#             result = await get_controller_info(controller, token)
#             outputlist.append(result)
#     return output
    result = await get_all_controllers()
    return [c for c in result]


async def get_controller_info(token, controller):
    if controller.c_access is not None:
        models = await get_models_info(controller)
        users = await get_users_controller(token, controller)
        result = {'name': controller.c_name, 'type': controller.c_token.type, 'models': models,
                  'users': users}
    else:
        result = None
    return result


async def c_access_exists(access):
    return access in ['login', 'add-model', 'superuser']


#libjuju : nog geen wrapper geschreven voor get_users()
async def get_controller_superusers(controller):
    try:
        con = controller.c_connection
        users = await con.get_users()
        return [u['properties']['username']['type'] for u in users if u['properties']['access']['type'] == 'superuser']
    except NotImplementedError:
        users = json.loads(output_pass(['juju', 'users', '--format', 'json'], controller.c_name))
        return [u['user-name'] for u in users if u['access'] == 'superuser']
    except json.decoder.JSONDecodeError as e:
        error = errors.cmd_error(e)
        abort(error[0], error[1])
###############################################################################
# MODEL FUNCTIONS
###############################################################################
async def get_all_models(controller):
    try:
        cont_conn = controller.c_connection
        models = await cont_conn.get_models()
        return [model.serialize()['model'].serialize() for model in models.serialize()['user-models']]
    except NotImplementedError:
        try:
            jujudata = JujuData()
            return list(jujudata.models()[controller.c_name])
        except FileNotFoundError:
            return []
    except json.decoder.JSONDecodeError as e:
        error = errors.cmd_error(e)
        abort(error[0], error[1])


async def model_exists(controller, modelname):
    all_models = await get_all_models(controller)
    for model in all_models:
        if model['name'] == modelname:
            return True
    return False


async def get_model_uuid(controller, model):
    for mod in await get_all_models(controller):
        if mod['name'] == model.m_name:
            return mod['uuid']


#TODO
async def get_model_access(model, controller, username):
    access = None
    try:
    #     controller = token.c_connection
    #     models = await controller.get_models()
    #     for model in models:
    #         model.get_info()
    # except NotImplementedError:
        for mod in json.loads(output_pass(['juju', 'models', '--format', 'json'], controller.c_name))['models']:
            if mod['name'] == model.m_name and username in mod['users'].keys():
                access = mod['users'][username]['access']
                break
        return access
    except json.decoder.JSONDecodeError as e:
        error = errors.cmd_error(e)
        abort(error[0], error[1])


# async def m_access_exists(access):
#     return access in ['read', 'write', 'admin']


async def get_models_info(controller):
    return [(m['name']) for m in await get_all_models(controller)]


async def get_model_info(token, controller, model):
    if model.m_access is not None:
        users = await get_users_model(token, model, controller)
        ssh = await get_ssh_keys(model, controller)
        applications = await get_applications_info(model)
        machines = await get_machines_info(model)
        result = {'name': model.m_name, 'users': users, 'ssh-keys': ssh,
                  'applications': applications, 'machines': machines}
    else:
        result = None
    return result


async def get_ssh_keys(model, controller):
    try:
        model_con = model.m_connection
        res = await model_con.get_ssh_key(False)
        return res.serialize()['results'][0].serialize()
    except NotImplementedError:
        return output_pass(['juju', 'ssh-keys', '--full'], controller.c_name, model.m_name).split('\n')[1:-1]


async def get_applications_info(model):
    try:
        model_con = model.m_connection
        data = model_con.state.state
        result = []
        apps = data.get('application', {})
        for app in apps.keys():
            result.append(await get_application_info(model, app))
        return result
    except json.decoder.JSONDecodeError as e:
        error = errors.cmd_error(e)
        abort(error[0], error[1])


async def get_units_info(model, application):
    try:
        mod = model.m_connection
        data = mod.state.state['unit']
        units = []
        result = []
        for unit in data.keys():
            if unit.startswith(application):
                units.append(data[unit][0])
        for u in units:
            ports = await get_unit_ports(u)
            result.append({'name': u['name'],
                           'machine': u['machine-id'],
                           'ip': u['public-address'],
                           'ports': ports})
        return result
    except json.decoder.JSONDecodeError as e:
        error = errors.cmd_error(e)
        abort(error[0], error[1])


#libjuju geen manier om gui te verkrijgen of juju gui methode
async def get_gui_url(controller, model):
    try:
        return 'https://{}/gui/{}'.format(controller.url, model.m_uuid)
    except json.decoder.JSONDecodeError as e:
        error = errors.cmd_error(e)
        abort(error[0], error[1])


async def create_model(token, controller, modelname, ssh_key=None):
    con_con = controller.c_connection
    await con_con.add_model(modelname)
    model = Model_Connection()
    await model.set_model(token, controller, modelname)
    if ssh_key is not None:
        await add_ssh_key(token, model, ssh_key)
    await model_grant(model, token.username, 'admin')
    cont = await get_controller_superusers(controller)
    for user in cont:
        await model_grant(model, user, 'admin')
    return model


async def delete_model(controller, model):
    try:
        controller_con = controller.c_connection
        await controller_con.destroy_models(model.m_uuid)
    except NotImplementedError:
        output_pass(['juju', 'destroy-model', '-y', '{}:{}'.format(controller.c_name, model.m_name)])


async def add_ssh_key(token, model, ssh_key):
    model_con = model.m_connection
    await model_con.add_ssh_key(token.username, ssh_key)


async def remove_ssh_key(token, model, ssh_key):
    model_con = model.m_connection
    await model_con.remove_ssh_key(token.username, ssh_key)

#####################################################################################
# Machines FUNCTIONS
#####################################################################################
async def get_machines_info(model):
    try:
        model_con = model.m_connection
        data = model_con.state.machines.keys()
        result = []
        for m in data:
            if not 'lxd' in m:
                res = await get_machine_info(model, m)
                result.append(res)
        return result
    except json.decoder.JSONDecodeError as e:
        error = errors.cmd_error(e)
        abort(error[0], error[1])


async def get_machine_entity(model, machine):
    model_con = model.m_connection
    for app in model_con.state.machines.items():
        if app[0] == machine:
            return app[1]


async def get_machine_info(model, machine):
    try:
        model_con = model.m_connection
        data = model_con.state.state['machine']
        machine_data = data[machine][0]
        if machine_data is None:
            result = {'name': machine, 'instance-id': 'Unknown', 'ip': 'Unknown', 'series': 'Unknown', 'containers': 'Unknown'}
            return result
        containers = []
        if not 'lxd' in machine:
            lxd = []
            for key in data.keys():
                if key.startswith('{}/lxd'.format(machine)):
                    lxd.append(key)
            if lxd != []:
                for cont in lxd:
                    cont_data = data[cont][0]
                    ip = await get_machine_ip(cont_data, 'local_cloud')
                    containers.append({'name': cont, 'instance-id': cont_data['instance-id'], 'ip': ip, 'series': cont_data['series']})
            mach_ip = await get_machine_ip(machine_data, 'public')
            result = {'name': machine, 'instance-id': machine_data['instance-id'], 'ip': mach_ip, 'series': machine_data['series'], 'containers': containers}
        else:
            mach_ip = await get_machine_ip(machine_data, 'local_cloud')
            result = {'name': machine, 'instance-id': machine_data['instance-id'], 'ip': mach_ip, 'series': machine_data['series']}
    except KeyError:
        result = {'name': machine, 'instance-id': 'Unknown', 'ip': 'Unknown', 'series': 'Unknown', 'containers': 'Unknown'}
    except json.decoder.JSONDecodeError as e:
        error = errors.cmd_error(e)
        abort(error[0], error[1])
    return result


async def get_machine_ip(machine_data, cloud):
    for dns in machine_data['addresses']:
        if dns['scope'] == cloud:
            dns_name = dns['value']
    return dns_name


async def add_machine(model, ser=None, cont=None):
    model_con = model.m_connection
    await model_con.add_machine(series=ser, constraints=cont)


async def machine_exists(model, machine):
    try:
        model_con = model.m_connection
        data = model_con.state.state['machine'].keys()
        return machine in data
    except json.decoder.JSONDecodeError as e:
        error = errors.cmd_error(e)
        abort(error[0], error[1])


async def get_machine_series(model, machine):
    try:
        data = await get_machine_info(model, machine)
        return data['series']
    except json.decoder.JSONDecodeError as e:
        error = errors.cmd_error(e)
        abort(error[0], error[1])


# async def machine_matches_series(model, machine, series):
#     if machine is None or series is None:
#         return True
#     else:
#         return series == await get_machine_series(model, machine)


async def remove_machine(model, machine):
    machine = await get_machine_entity(model, machine)
    machine.destroy(force=True)


#####################################################################################
# APPLICATION FUNCTIONS
#####################################################################################
async def app_exists(token, controller, model, app_name):
    try:
        model_info = await get_model_info(token, controller, model)
        for app in model_info['applications']:
            if app['name'] == app_name:
                return True
        return False
    except json.decoder.JSONDecodeError as e:
        error = errors.cmd_error(e)
        abort(error[0], error[1])


async def deploy_bundle(model, bundle):
    with open('{}/bundle/bundle.yaml'.format(settings.SOJOBO_API_DIR), 'w+') as outfile:
        yaml.dump(bundle, outfile, default_flow_style=False)
    model_con = model.m_connection
    await model_con.deploy('{}/bundle/'.format(settings.SOJOBO_API_DIR), series=bundle['series'])


async def deploy_app(model, app_name, ser=None, tar=None):
    model_con = model.m_connection
    await model_con.deploy(app_name, series=ser, to=tar)


async def get_application_entity(model, app_name):
    model_con = model.m_connection
    for app in model_con.state.applications.items():
        if app[0] == app_name:
            return app[1]


async def remove_app(model, app_name):
    app = await get_application_entity(model, app_name)
    if app is not None:
        await app.remove()


async def get_application_info(model, applic):
    try:
        model_con = model.m_connection
        data = model_con.state.state
        res1 = {}
        for application in data['application'].items():
            if application[0] == applic:
                app = application[1]
                res1 = {'name': app[0]['name'], 'relations': [], 'charm': app[0]['charm-url'], 'exposed': app[0]['exposed'],
                        'series': app[0]['charm-url'].split(":")[1].split("/")[0], 'status': app[0]['status']['current']}
                for rels in data['relation'].values():
                    keys = rels[0]['key'].split(" ")
                    if len(keys) == 1 and app[0]['name'] == keys[0].split(":")[0]:
                        res1['relations'].extend([{'interface': keys[0].split(":")[1], 'with': keys[0].split(":")[0]}])
                    elif len(keys) == 2 and app[0]['name'] == keys[0].split(":")[0]:
                        res1['relations'].extend([{'interface': keys[1].split(":")[1], 'with': keys[1].split(":")[0]}])
                    elif len(keys) == 2 and app[0]['name'] == keys[1].split(":")[0]:
                        res1['relations'].extend([{'interface': keys[0].split(":")[1], 'with': keys[0].split(":")[0]}])
                res1['units'] = await get_units_info(model, app[0]['name'])
        return res1
    except json.decoder.JSONDecodeError as e:
        error = errors.cmd_error(e)
        abort(error[0], error[1])


async def get_unit_info(model, application, unitnumber):
    data = await get_application_info(model, application)
    for u in data['units']:
        if u['name'] == '{}/{}'.format(application, unitnumber):
            return u
    return {}


# def unit_exists(token, application, unitnumber):
#     data = get_application_info(token, application)
#     for u in data['units']:
#         if u['name'] == '{}/{}'.format(application, unitnumber):
#             return u


async def add_unit(model, app_name, target=None):
    application = await get_application_entity(model, app_name)
    await application.add_unit(count=1, to=target)


async def remove_unit(model, application, unit_number):
    app = await get_application_entity(model, application)
    unit = '{}/{}'.format(application, unit_number)
    await app.destroy_unit(unit)


async def get_unit_ports(unit):
    ports = []
    for port in unit['ports']:
        ports.append(port)
    return ports


async def get_relations_info(model):
    data = await get_applications_info(model)
    return [{'name': a['name'], 'relations': a['relations']} for a in data]


async def add_relation(model, app1, app2):
    model_con = model.m_connection
    await model_con.add_relation(app1, app2)


async def remove_relation(model, app1, app2):
    model_con = model.m_connection
    data = model_con.state.state
    application = await get_application_entity(model, app1)
    if app1 == app2:
        for relation in data['relation'].items():
            keys = relation[1][0]['keys'].split(':')
            await application.destroy_relation(keys[1], '{}:{}'.format(keys[0], keys[1]))
    else:
        for relation in data['relation'].items():
            keys = relation[1][0]['keys'].split(' ')
            if keys[0].startswith(app1):
                await application.destroy_relation(keys[0].split(':')[1], keys[1])
            elif keys[1].startswith(app1):
                await application.destroy_relation(keys[1].split(':')[1], keys[0])


# async def app_supports_series(app_name, series):
#     if series is None:
#         supports = True
#     elif 'local:' in app_name:
#         with open('{}/{}/metadata.yaml'.format(settings.LOCAL_CHARM_DIR, app_name.split(':')[1])) as data:
#             supports = series in yaml.load(data)['series']
#     else:
#         supports = False
#         data = requests.get('https://api.jujucharms.com/v4/{}/expand-id'.format(app_name))
#         for value in json.loads(data.text):
#             if series in value['Id']:
#                 supports = True
#                 break
#     return supports
###############################################################################
# USER FUNCTIONS
###############################################################################
async def create_user(token, con, username, password):
    try:
        await con.c_connection.add_user(username)
        await change_user_password(con, username, password)
        await controller_grant(con, username, 'login')
    except NotImplementedError:
        for controller in list(await get_all_controllers()):
            output_pass(['juju', 'add-user', username], controller)
            output_pass(['juju', 'revoke', username, 'login'], controller)
            check_output(['juju', 'change-user-password', username, '-c', controller],
                         input=bytes('{}\n{}\n'.format(password, password), 'utf-8'))


async def delete_user(controller, username):
    try:
        con = controller.c_connection
        await con.disable_user(username)
    except NotImplementedError:
        for control in await get_all_controllers():
            output_pass(['juju', 'remove-user', username, '-y'], control)


async def change_user_password(controller, username, password):
    try:
        cont = controller.c_connection
        await cont.change_user_password(username, password)
    except NotImplementedError:
        for control in get_all_controllers():
            check_output(['juju', 'change-user-password', username, '-c', control],
                         input=bytes('{}\n{}\n'.format(password, password), 'utf-8'))


#libjuju: nog gene methode om get_all_users te implementeren
async def get_users_controller(token, controller):
    try:
        if controller.c_access == 'superuser':
            data = json.loads(output_pass(['juju', 'list-users', '--format', 'json'], controller.c_name))
            users = [{'name': u['user-name'], 'access': u['access']} for u in data]
        elif controller.c_access is not None:
            users = [{'name': token.username, 'access': controller.c_access}]
        else:
            users = None
        return users
    except json.decoder.JSONDecodeError as e:
        error = errors.cmd_error(e)
        abort(error[0], error[1])


#libjuju: nog gene methode om get_all_users te implementeren
async def get_users_model(token, model, controller):
    try:
        if model.m_access == 'admin' or model.m_access == 'write':
            data = json.loads(output_pass(['juju', 'models', '--format', 'json'], controller.c_name))
            for mod in data['models']:
                if mod['name'] == model.m_name:
                    users_info = mod['users']
                    break
            users = [{'name': k, 'access': v['access']} for k, v in users_info.items()]
        elif model.m_access is not None:
            users = [{'name': token.username, 'access': model.m_access}]
        else:
            users = None
        return users
    except json.decoder.JSONDecodeError as e:
        error = errors.cmd_error(e)
        abort(error[0], error[1])


async def controller_grant(controller, username, access):
    cont = controller.c_connection
    await cont.grant(username, access)


async def controller_revoke(controller, username):
    cont = controller.c_connection
    await cont.revoke(username)


async def model_grant(model, username, access):
    model_con = model.m_connection
    await model_con.grant(username, access)


async def model_revoke(model, username):
    model_con = model.m_connection
    await model_con.revoke(username)


async def user_exists(username):
    return username == settings.JUJU_ADMIN_USER or username in await get_all_users()


#libjuju: geen andere methode om users op te vragen atm
async def get_all_users():
    try:
        controller = list(await get_all_controllers())
        users = json.loads(output_pass(['juju', 'users', '--all', '--format', 'json'], controller[0]))
        result = [user['user-name'] for user in users]
    except IndexError:
        result = [settings.JUJU_ADMIN_USER]
    except json.decoder.JSONDecodeError as e:
        error = errors.cmd_error(e)
        abort(error[0], error[1])
    return result


async def get_users_info(token):
    result = []
    for u in await get_all_users():
        ui = await get_user_info(token, u)
        result.append(ui)
    return result


async def get_user_info(token, username):
    user_acc = await get_controllers_access(token)
    return {'name': username, 'controllers': user_acc}


async def get_controllers_access(token):
    controllers = []
    for controller in await get_all_controllers():
        cont_obj = Controller_Connection()
        access = await get_controller_access(await cont_obj.set_controller(token, controller), token.username)
        if access is not None:
            model_acc = await get_models_access(controller, token)
            controllers.append({'name': controller, 'type': token.c_token.type, 'access': access,
                                'models': model_acc})
    return controllers


async def get_ucontroller_access(controller, token, username):
    acc = await get_controller_access(controller, username)
    mod = await get_models_access(controller, token)
    return {'name': controller.c_name,
            'access': acc,
            'models': mod}


async def get_models_access(controller, token):
    models = []
    for model in await get_all_models(controller):
        model_con = Model_Connection()
        await model_con.set_model(token, controller, model)
        access = await get_model_access(model_con, controller, token.username)
        if access is not None:
            models.append({'name': model, 'access': access})
    return models


async def get_umodel_access(controller, model, username):
    mod_acc = await get_model_access(model, controller, username)
    return {'name': model.m_name, 'access': mod_acc}

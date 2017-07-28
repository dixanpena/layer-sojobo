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
import asyncio
from importlib import import_module
import os
import tempfile
import shutil
from subprocess import check_output, check_call
import json
import yaml
from flask import abort, Response
from juju import tag
from juju.client.connection import JujuData
from juju.controller import Controller
from juju.errors import JujuAPIError, JujuError
from juju.model import Model
from sojobo_api.api import w_errors as errors, w_datastore as datastore
from sojobo_api import settings
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
        self.m_access = await get_model_access(self.m_name, controller.c_name, token.username)
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
        self.c_type = None
        self.public_ip = None

    async def set_controller(self, token, c_name):
        self.c_type = await get_controller_type(c_name)
        c_endpoint = get_controller_types()[self.c_type].get_public_url(c_name)
        self.url = c_endpoint
        self.c_name = c_name
        self.c_token = getattr(get_controller_types()[self.c_type], 'Token')(c_endpoint, token.username, token.password)
        if self.c_connection is not None:
            await self.c_connection.disconnect()
        self.c_connection = await connect_controller(self, token)
        self.public_ip = await get_public_ip_controller(self.c_connection)
        self.c_access = await get_controller_access(self, token.username)
        return self

    async def disconnect(self):
        if self.c_connection is not None:
            await self.c_connection.disconnect()


def get_controller_types():
    c_list = {}
    for f_path in os.listdir('{}/controllers'.format(settings.SOJOBO_API_DIR)):
        if 'controller_' in f_path and '.pyc' not in f_path:
            name = f_path.split('.')[0]
            c_list[name.split('_')[1]] = import_module('sojobo_api.controllers.{}'.format(name))
    return c_list


def execute_task(command, *args, **kwargs):
    loop = asyncio.get_event_loop()
    loop.set_debug(False)
    result = loop.run_until_complete(command(*args, **kwargs))
    return result


def create_response(http_code, return_object, is_json=False):
    if not is_json:
        return_object = json.dumps(return_object)
    return Response(
        return_object,
        status=http_code,
        mimetype='application/json',
    )


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


async def authenticate(api_key, auth):
    if api_key == settings.API_KEY:
        token = JuJu_Token(auth)
        if token.is_admin:
            return token
        else:
            controller = Controller_Connection()
            try:
                cont_name = list(await get_all_controllers())[0]
                await controller.set_controller(token, cont_name)
                await controller.disconnect()
                return token
            except JujuAPIError:
                await controller.disconnect()
                error = errors.unauthorized()
                abort(error[0], error[1])
    else:
        error = errors.unauthorized()
        abort(error[0], error[1])


async def authorize(token, controller, model=None):
    if not await controller_exists(controller):
        error = errors.does_not_exist('controller')
        abort(error[0], error[1])
    else:
        con_access = datastore.get_controller_access(controller, token.username)
        if con_access not in ['login', 'add-model', 'superuser']:
            error = errors.does_not_exist('controller')
            abort(error[0], error[1])
        else:
            con = Controller_Connection()
            await con.set_controller(token, controller)
    if model and not await model_exists(con, model):
        error = errors.does_not_exist('controller')
        abort(error[0], error[1])
    elif model:
        mod_access = datastore.get_model_access(controller, model, token.username)
        if mod_access not in ['read', 'write', 'admin']:
            error = errors.does_not_exist('model')
            abort(error[0], error[1])
        else:
            mod = Model_Connection()
            await mod.set_model(token, con, model)
            return con, mod
    return con
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


async def create_controller(c_type, name, region, credentials):
    get_controller_types()[c_type].create_controller(name, region, credentials)
    pswd = settings.JUJU_ADMIN_PASSWORD
    check_output(['juju', 'change-user-password', 'admin', '-c', name], input=bytes('{}\n{}\n'.format(pswd, pswd), 'utf-8'))
    datastore.create_controller(name, c_type)
    datastore.create_user('admin')
    datastore.add_user_to_controller(name, 'admin', 'superuser')
    controller = Controller_Connection()
    return controller


async def generate_cred_file(c_type, name, credentials):
    return get_controller_types()[c_type].generate_cred_file(name, credentials)


async def delete_controller(con):
    #controller = con.c_connection
    #await controller.destroy(True)
    check_output(['/snap/bin/juju', 'login', con.c_name, '-u', settings.JUJU_ADMIN_USER], input=bytes('{}\n'.format(settings.JUJU_ADMIN_PASSWORD), 'utf-8'))
    check_call(['/snap/bin/juju', 'destroy-controller', '-y', con.c_name, '--destroy-all-models'])
    check_call(['/snap/bin/juju', 'remove-credential', con.c_type, con.c_name])
    datastore.destroy_controller(con.c_name)


async def get_all_controllers():
    return datastore.get_all_controllers()


async def controller_exists(c_name):
    return c_name in list(await get_all_controllers())


async def get_controller_access(con, username):
    return datastore.get_controller_access(con.c_name, username)


async def get_controllers_info():
    jujudata = JujuData()
    result = jujudata.controllers()
    return result


async def get_controller_info(controller):
    if controller.c_access is not None:
        models = await get_models_info(controller)
        users = await get_users_controller(controller.c_name)
        result = {'name': controller.c_name, 'type': controller.c_token.type, 'models': models,
                  'users': users}
    else:
        result = None
    return result


async def get_controller_superusers(controller):
    users = datastore.get_controller_users(controller)
    result = []
    for user in users:
        if datastore.get_controller_access(controller, user['name']) == 'superuser':
            result.append(user['name'])
    return result


async def get_controller_type(c_name):
    controllers = await get_controllers_info()
    return controllers[c_name]['cloud']
###############################################################################
# MODEL FUNCTIONS
###############################################################################
async def get_all_models(controller):
    cont_conn = controller.c_connection
    models = await cont_conn.get_models()
    return [model.serialize()['model'].serialize() for model in models.serialize()['user-models']]


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


async def get_model_access(model, controller, username):
    return datastore.get_model_access(controller, model, username)


async def get_models_info(controller):
    return [(m['name']) for m in await get_all_models(controller)]


async def get_model_info(token, controller, model):
    if model.m_access is not None:
        users = await get_users_model(token, model, controller)
        ssh = await get_ssh_keys(model)
        applications = await get_applications_info(model)
        machines = await get_machines_info(model)
        gui = await get_gui_url(controller, model)
        credentials = await get_model_creds(model)
        result = {'name': model.m_name, 'users': users, 'ssh-keys': ssh,
                  'applications': applications, 'machines': machines, 'juju-gui-url' : gui,
                  'status': datastore.check_model_state(controller.c_name, model.m_name), 'credentials' : credentials}
    else:
        result = None
    return result


async def get_model_creds(model):
    model_con = model.m_connection
    info = await model_con.get_info()
    cloud_cred = info.serialize()['cloud-credential-tag']
    cloud_result = tag.untag('cloudcred-', cloud_cred)
    return get_cloud_response(cloud_result)


def get_cloud_response(data):
    values = data.split('_')
    if len(values) == 3:
        result = {'cloud' : values[0], 'user' : values[1], 'credential-name' : values[2]}
        return result
    return None


async def get_ssh_keys(model):
    model_con = model.m_connection
    res = await model_con.get_ssh_key(False)
    return res.serialize()['results'][0].serialize()


async def get_applications_info(model):
    model_con = model.m_connection
    data = model_con.state.state
    result = []
    apps = data.get('application', {})
    for app in apps.keys():
        result.append(await get_application_info(model, app))
    return result


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
                           'public-ip': u['public-address'],
                           'private-ip': u['private-address'],
                           'series': u['series'],
                           'ports': ports})
        return result
    except KeyError:
        return []


async def get_public_ip_controller(controller):
    servers = controller.connection.info['servers']
    for server_list in servers:
        for server in server_list:
            if server['scope'] == 'public' and server['type'] == 'ipv4':
                return server['value']



#libjuju geen manier om gui te verkrijgen of juju gui methode
async def get_gui_url(controller, model):
    return 'https://{}:17070/gui/{}'.format(controller.public_ip, model.m_uuid)


async def create_model(token, controller, modelname, ssh_key=None):
    con_con = controller.c_connection
    await con_con.add_model(modelname)
    datastore.set_model_access(controller.c_name, modelname, token.username, 'admin')
    model = Model_Connection()
    cont = await get_controller_superusers(controller.c_name)
    await model.set_model(token, controller, modelname)
    for user in cont:
        if not user == token.username:
            await model_grant(model, user, 'admin')
            datastore.set_model_access(controller.c_name, modelname, user, 'admin')
    if ssh_key is not None:
        await add_ssh_key(token, model, ssh_key)
    return model


async def delete_model(controller, model):
    controller_con = controller.c_connection
    datastore.delete_model(controller.c_name, model.m_name)
    await controller_con.destroy_models(model.m_uuid)


async def add_ssh_key(token, model, ssh_key):
    model_con = model.m_connection
    await model_con.add_ssh_key(token.username, ssh_key)


async def remove_ssh_key(token, model, ssh_key):
    model_con = model.m_connection
    await model_con.remove_ssh_key(token.username, ssh_key)


async def connect_to_model(token, controller, modelname):
    model_con = Model_Connection()
    await model_con.set_model(token, controller, modelname)
    return model_con
#####################################################################################
# Machines FUNCTIONS
#####################################################################################
async def get_machines_info(model):
    model_con = model.m_connection
    data = model_con.state.machines.keys()
    result = []
    for m in data:
        if not 'lxd' in m:
            res = await get_machine_info(model, m)
            result.append(res)
    return result


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
        if machine_data['agent-status']['current'] == 'error' and machine_data['addresses'] is None:
            result = {'name': machine, 'Error': machine_data['agent-status']['message']}
            return result
        if machine_data is None:
            result = {'name': machine, 'instance-id': 'Unknown', 'ip': 'Unknown', 'series': 'Unknown', 'containers': 'Unknown', 'hardware-characteristics' : 'unknown'}
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
                    ip = await get_machine_ip(cont_data)
                    containers.append({'name': cont, 'instance-id': cont_data['instance-id'], 'ip': ip, 'series': cont_data['series']})
            mach_ip = await get_machine_ip(machine_data)
            result = {'name': machine, 'instance-id': machine_data['instance-id'], 'ip': mach_ip, 'series': machine_data['series'], 'hardware-characteristics' : machine_data['hardware-characteristics'], 'containers': containers}
        else:
            mach_ip = await get_machine_ip(machine_data)
            result = {'name': machine, 'instance-id': machine_data['instance-id'], 'ip': mach_ip, 'series': machine_data['series'], 'hardware-characteristics' : machine_data['hardware-characteristics']}
    except KeyError:
        result = {'name': machine, 'instance-id': 'Unknown', 'ip': 'Unknown', 'series': 'Unknown', 'containers': 'Unknown', 'hardware-characteristics' : 'unknown'}
    return result


async def get_machine_ip(machine_data):
    mach_ips = {'internal_ip' : 'unknown', 'external_ip' : 'unknown'}
    if machine_data['addresses'] is None:
        return mach_ips
    for machine in machine_data['addresses']:
        if machine['scope'] == 'public':
            mach_ips['external_ip'] = machine['value']
        elif machine['scope'] == 'local-cloud':
            mach_ips['internal_ip'] = machine['value']
    return mach_ips


async def add_machine(model, ser=None, cont=None):
    model_con = model.m_connection
    await model_con.add_machine(series=ser, constraints=cont)


async def machine_exists(model, machine):
    model_con = model.m_connection
    data = model_con.state.state['machine'].keys()
    return machine in data


async def get_machine_series(model, machine):
    data = await get_machine_info(model, machine)
    return data['series']


async def remove_machine(model, machine):
    machine = await get_machine_entity(model, machine)
    await machine.destroy(force=True)


#####################################################################################
# APPLICATION FUNCTIONS
#####################################################################################
async def app_exists(token, controller, model, app_name):
    model_info = await get_model_info(token, controller, model)
    for app in model_info['applications']:
        if app['name'] == app_name:
            return True
    return False


async def deploy_bundle(model, bundle):
    dirpath = tempfile.mkdtemp()
    os.mkdir('{}/bundle'.format(dirpath))
    with open('{}/bundle/bundle.yaml'.format(dirpath), 'w+') as outfile:
        yaml.dump(bundle, outfile, default_flow_style=False)
    model_con = model.m_connection
    if 'series' in bundle.keys():
        await model_con.deploy('{}/bundle/'.format(dirpath), series=bundle['series'])
    await model_con.deploy('{}/bundle/'.format(dirpath))
    shutil.rmtree(dirpath)


async def deploy_app(model, app_name, name=None, ser=None, tar=None, con=None, num_of_units=1):
    try:
        model_con = model.m_connection
        await model_con.deploy(app_name, application_name=name, series=ser, to=tar, config=con, num_units=num_of_units)
    except JujuError as e:
        if e == 'subordinate application must be deployed without units':
            await model_con.deploy(app_name, application_name=name, series=ser, to=tar, config=con, num_units=0)



async def check_if_exposed(model, app_name, exposed=True):
    app_info = await get_application_info(model, app_name)
    if app_info['exposed'] == exposed:
        return True
    return False


async def expose_app(model, app_name):
    app = await get_application_entity(model, app_name)
    await app.expose()


async def unexpose_app(model, app_name):
    app = await get_application_entity(model, app_name)
    await app.expose()


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
    model_con = model.m_connection
    data = model_con.state.state
    res1 = {}
    for application in data['application'].items():
        if application[0] == applic:
            app = application[1]
            res1 = {'name': app[0]['name'], 'relations': [], 'charm': app[0]['charm-url'], 'exposed': app[0]['exposed'],
                    'status': app[0]['status']}
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
            keys = relation[1][0]['key'].split(':')
            await application.destroy_relation(keys[1], '{}:{}'.format(keys[0], keys[1]))
    else:
        for relation in data['relation'].items():
            keys = relation[1][0]['key'].split(' ')
            if len(keys) > 1:
                if keys[0].startswith(app1):
                    await application.destroy_relation(keys[0].split(':')[1], keys[1])
                elif keys[1].startswith(app1):
                    await application.destroy_relation(keys[1].split(':')[1], keys[0])

async def set_application_config(mod, app_name, config):
    app = get_application_entity(mod, app_name)
    await app.set_config(config)


async def get_application_config(mod, app_name):
    app = get_application_entity(mod, app_name)
    return await app.get_config()

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
async def create_user(con, username, password):
    await con.c_connection.add_user(username)
    await change_user_password(con, username, password)
    datastore.add_user_to_controller(con.c_name, username, 'login')


async def delete_user(controller, username):
    con = controller.c_connection
    datastore.remove_user_from_controller(controller.c_name, username)
    await con.disable_user(username)


async def enable_user(controller, username):
    con = controller.c_connection
    datastore.add_user_to_controller(controller.c_name, username, 'login')
    await con.enable_user(username)


async def change_user_password(controller, username, password):
    cont = controller.c_connection
    await cont.change_user_password(username, password)


async def get_users_controller(controller):
    cont_info = datastore.get_controller(controller)
    return cont_info['users']


async def get_users_model(token, model, controller):
    if model.m_access == 'admin' or model.m_access == 'write':
        users = datastore.get_users_model(controller.c_name, model.m_name)
    elif model.m_access == 'read':
        users = [{'name': token.username, 'access': model.m_access}]
    else:
        users = None
    return users


async def controller_grant(controller, username, access):
    cont = controller.c_connection
    await cont.grant(username, acl=access)


async def controller_revoke(controller, username):
    cont = controller.c_connection
    await cont.revoke(username)


async def model_grant(model, username, access):
    model_con = model.m_connection
    await model_con.grant(username, acl=access)


async def model_revoke(model, username):
    model_con = model.m_connection
    await model_con.revoke(username)

async def user_exists(username):
    return username == settings.JUJU_ADMIN_USER or username in await get_all_users()


#libjuju: geen andere methode om users op te vragen atm
async def get_all_users():
    return datastore.get_all_users()


async def get_users_info():
    result = []
    for u in await get_all_users():
        ui = await get_user_info(u)
        if ui['active']:
            result.append(ui)
    return result


async def get_user_info(username):
    u_info = datastore.get_user(username)
    for conts in u_info['access']:
        con = list(conts.keys())[0]
        c_type = await get_controller_type(con)
        conts[con]['type'] = c_type
    u_info.pop('_id', None)
    return u_info


async def get_controllers_access(usr):
    user = await get_user_info(usr)
    return user['access']


async def get_ucontroller_access(controller, username):
    access = await get_controllers_access(username)
    for acc in access:
        if list(acc.keys())[0] == controller.c_name:
            return acc


async def get_models_access(controller, name):
    return datastore.get_models_access(controller.c_name, name)
#########################
# extra Acces checks
#########################
def c_access_exists(access):
    return access in ['login', 'add-model', 'superuser']


def m_access_exists(access):
    return access in ['read', 'write', 'admin']


def check_access(access):
    acc = access.lower()
    if c_access_exists(acc) or m_access_exists(acc):
        return acc
    else:
        error = errors.invalid_access('access')
        abort(error[0], error[1])


async def check_same_access(user, new_access, controller, model=None):
    if model is None:
        old_acc = await get_ucontroller_access(controller, user)
        return old_acc == new_access
    else:
        old_acc = await get_model_access(model, controller, user)
        return old_acc == new_access

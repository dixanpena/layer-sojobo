# Copyright (C) 2017 Qrama
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
# pylint: disable=c0111,c0301,c0325,c0326,w0406,e0401,e0611
###############################################################################
# USER FUNCTIONS
###############################################################################
import logging
from flask import request, Blueprint

from sojobo_api.api import w_errors as errors, w_juju as juju
from sojobo_api.api.w_juju import execute_task


USERS = Blueprint('users', __name__)
LOGGER = logging.getLogger("api_users")
LOGGER.setLevel(logging.DEBUG)
WS_LOGGER = logging.getLogger('websockets.protocol')
WS_LOGGER.setLevel(logging.DEBUG)

def get():
    return USERS

@USERS.before_app_first_request
def initialize():
    hdlr = logging.FileHandler('/opt/sojobo_api/log/api_users.log')
    hdlr.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
    hdlr.setFormatter(formatter)
    LOGGER.addHandler(hdlr)
    WS_LOGGER.addHandler(hdlr)


@USERS.route('/login', methods=['POST'])
def login():
    try:
        execute_task(juju.authenticate, request.headers['api-key'], request.authorization)
        code, response = 200, 'Success'
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@USERS.route('/', methods=['GET'])
def get_users_info():
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization)
        code, response = 200, execute_task(juju.get_users_info, token)
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)

@USERS.route('/', methods=['POST'])
def create_user():
    data = request.json
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization)
        user = data['username']
        m = re.match('^[0-9a-zA-Z]([0-9a-zA-Z.-]*[0-9a-zA-Z])$', user)
        if not(m) and m.end() != len(user):
            code, response = 400, "username does not have the correct format."
        elif token.is_admin:
            if execute_task(juju.user_exists, user):
                code, response = errors.already_exists('user')
            elif data['password']:
                execute_task(juju.create_user, token, user, data['password'])
                code, response = 202, 'User {} is being created'.format(user)
            else:
                code, response = errors.empty()
        else:
            code, response = errors.unauthorized()
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@USERS.route('/<user>', methods=['GET'])
def get_user_info(user):
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization)
        if user == token.username or token.is_admin:
            if execute_task(juju.user_exists, user):
                code, response = 200, execute_task(juju.get_user_info, user)
            else:
                code, response = errors.does_not_exist('user')
        else:
            code, response = errors.unauthorized()
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@USERS.route('/<user>', methods=['PUT'])
def change_user_password(user):
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization)
        if user == token.username or token.is_admin:
            if execute_task(juju.user_exists, user):
                pwd = request.json['password']
                if pwd:
                    execute_task(juju.change_user_password, token, user, pwd)
                    code, response = 200, 'succesfully changed password for user {}'.format(user)
                else:
                    code, response = errors.empty()
            else:
                code, response = errors.does_not_exist('user')
        else:
            code, response = errors.unauthorized()
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@USERS.route('/<user>', methods=['DELETE'])
def delete_user(user):
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization)
        if token.is_admin:
            if execute_task(juju.user_exists, user):
                if user != 'admin':
                    execute_task(juju.delete_user, token, user)
                    code, response = 200, 'User {} succesfully removed'.format(user)
                else:
                    code, response = 403, 'This would remove the admin from the system!'
            else:
                code, response = errors.does_not_exist('user')
        else:
            code, response = errors.unauthorized()
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@USERS.route('/<user>/ssh-keys', methods=['GET'])
def get_ssh_keys(user):
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization)
        if token.is_admin or token.username == user:
            code, response = 200, execute_task(juju.get_ssh_keys_user, user)
        else:
            code, response = errors.unauthorized()
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@USERS.route('/<user>/ssh-keys', methods=['PUT'])
def update_ssh_keys(user):
    data = request.json
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization)
        user = juju.check_input(user)
        if token.is_admin or token.username == user:
            execute_task(juju.update_ssh_keys_user, user, data)
            code, response = 202, 'Process being handeled'
        else:
            code, response = errors.unauthorized()
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@USERS.route('/<user>/credentials', methods=['GET'])
def get_credentials(user):
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization)
        usr = juju.check_input(user)
        if token.is_admin or token.username == usr:
            code, response = 200, juju.execute_task(juju.get_credentials, token, usr)
        else:
            code, response = errors.unauthorized()
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@USERS.route('/<user>/credentials', methods=['POST'])
def add_credential(user):
    data = request.json
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization)
        usr = juju.check_input(user)
        if token.is_admin or token.username == usr:
            execute_task(juju.add_credential, usr, data['type'], data['name'], data['credential'])
            code, response = 202, 'Process being handeled'
        else:
            code, response = errors.unauthorized()
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)

@USERS.route('/<user>/credentials/<credential>', methods=['DELETE'])
def get_credential(user, credential):
    data = request.json
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization)
        usr = juju.check_input(user)
        if token.is_admin or token.username == usr:
            execute_task(juju.get_credential, usr, data['name'], credential)
            code, response = 202, 'Process being handeled'
        else:
            code, response = errors.unauthorized()
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)

@USERS.route('/<user>/credentials/<credential>', methods=['DELETE'])
def remove_credential(user, credential):
    data = request.json
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization)
        usr = juju.check_input(user)
        if token.is_admin or token.username == usr:
            execute_task(juju.remove_credential, usr, data['name'], credential)
            code, response = 202, 'Process being handeled'
        else:
            code, response = errors.unauthorized()
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@USERS.route('/<user>/controllers', methods=['GET'])
def get_controllers_access(user):
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization)
        usr = juju.check_input(user)
        if execute_task(juju.user_exists, usr):
            if token.is_admin or token.username == usr:
                code, response = 200, execute_task(juju.get_controllers_access, usr)
            else:
                code, response = errors.unauthorized()
        else:
            code, response = errors.does_not_exist('user')
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@USERS.route('/<user>/controllers/<controller>', methods=['GET'])
def get_ucontroller_access(user, controller):
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization)
        con = execute_task(juju.authorize, token, juju.check_input(controller))
        usr = juju.check_input(user)
        if execute_task(juju.user_exists, usr):
            if token.is_admin or token.username == usr:
                code, response = 200, execute_task(juju.get_ucontroller_access, con, usr)
            else:
                code, response = errors.unauthorized()
        else:
            code, response = errors.does_not_exist('user')
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@USERS.route('/<user>/controllers/<controller>', methods=['PUT'])
def grant_to_controller(user, controller):
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization)
        con = execute_task(juju.authorize, token, juju.check_input(controller))
        usr = juju.check_input(user)
        if (token.is_admin or con.c_access == 'superuser') and usr != 'admin':
            access = juju.check_access(request.json['access'])
            if execute_task(juju.user_exists, usr):
                execute_task(juju.add_user_to_controller, token, con, usr, access)
                code, response = 202, 'Process being handeled'
            else:
                code, response = errors.does_not_exist('user')
        else:
            code, response = errors.unauthorized()
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@USERS.route('/<user>/controllers/<controller>/models', methods=['GET'])
def get_models_access(user, controller):
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization)
        con = execute_task(juju.authorize, token, juju.check_input(controller))
        usr = juju.check_input(user)
        if execute_task(juju.user_exists, usr):
            if token.is_admin or token.username == usr:
                execute_task(con.connect, token)
                code, response = 200, execute_task(juju.get_models_access, con, usr)
                execute_task(con.disconnect)
            else:
                code, response = errors.unauthorized()
        else:
            code, response = errors.does_not_exist('user')
    except KeyError:
        code, response = errors. invalid_data()
    return juju.create_response(code, response)


@USERS.route('/<user>/controllers/<controller>/models', methods=['PUT'])
def grant_to_model(user, controller):
    try:
        data = request.json
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization)
        con = execute_task(juju.authorize, token, juju.check_input(controller))
        usr = juju.check_input(user)
        if (token.is_admin or con.c_access == 'superuser') and user != 'admin':
            if execute_task(juju.user_exists, user):
                execute_task(juju.set_models_access, token, con, usr, data)
                code, response = 202, 'Process being handeled'
            else:
                code, response = errors.does_not_exist('user')
        else:
            user_access = execute_task(juju.get_models_access, con, usr)
            if execute_task(juju.user_exists, usr):
                for mod in data:
                    if not mod['name'] in user_access:
                        return juju.create_response(errors.unauthorized())
                execute_task(juju.set_models_access, token, con, usr, data)
                code, response = 202, 'Process being handeled'
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@USERS.route('/<user>/controllers/<controller>/models/<model>', methods=['GET'])
def get_model_access(user, controller, model):
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization)
        con, mod = execute_task(juju.authorize, token, juju.check_input(controller), juju.check_input(model))
        usr = juju.check_input(user)
        if execute_task(juju.user_exists, usr):
            if token.is_admin or token.username == usr:
                access = execute_task(juju.get_model_access, mod.m_name, con.c_name, usr)
                code, response = 200, {'access' : access}
            else:
                code, response = errors.unauthorized()
        else:
            code, response = errors.does_not_exist('user')
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)


@USERS.route('/<user>/controllers/<controller>/models/<model>', methods=['DELETE'])
def revoke_from_model(user, controller, model):
    try:
        token = execute_task(juju.authenticate, request.headers['api-key'], request.authorization)
        con, mod = execute_task(juju.authorize, token, juju.check_input(controller), juju.check_input(model))
        usr = juju.check_input(user)
        if execute_task(juju.user_exists, usr):
            if (mod.m_access == 'admin' or mod.c_access == 'superuser') and user != 'admin':
                execute_task(con.connect, token)
                execute_task(mod.connect, token)
                execute_task(juju.remove_user_from_model, con, mod, usr)
                code, response = 200, 'Revoked access for user {} on model {}'.format(usr, model)
                execute_task(con.disconnect)
                execute_task(mod.disconnect)
            else:
                code, response = errors.unauthorized()
        else:
            code, response = errors.does_not_exist('user')
    except KeyError:
        code, response = errors.invalid_data()
    return juju.create_response(code, response)

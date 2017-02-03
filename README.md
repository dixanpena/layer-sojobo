# Introduction
This is the api for the Tengu platform. Besides providing all the necessary Tengu - commands, it also introduces
JuJu - wide users (instead of users on a controller-level) and the principle of an admin-user.
# Installation
There are 3 different setup options that can be specified in the config:
- http
- httpsletsencrypt (default)
- httpsclient
## http
This installs the Sojobo api running on http. **This is highly discouraged!!!**

## httpsletsencrypt
This is the default value. This means the client does not have it's own SSL certificates and free ones will be created with
LetsEncrypt. It setups the required nginx config to allow generation of the keys, and installs letsencrypt. Actual generating
of the certificates requires that the Sojobo-API is exposed and accessable on it's FQDN (Full Qualified Domain Name). If this is the case, the certificates can be generated with the following command `sudo letsencrypt certonly -a webroot --webroot-path=/var/www/html -d fqdn`. More info of the process can be found <a href="https://www.digitalocean.com/community/tutorials/how-to-secure-nginx-with-let-s-encrypt-on-ubuntu-16-04">here</a>.
**Setting up the cronjob for automatic renewal of the certificates must also be done manually (see above url)!**
When the certificates are generated, one can continue setting up https by running the command `juju config setup=httpsclient`.

## httpsclient
This option is used if the client already has its own SSL certifcates, or if they have been generated using LetsEncrypt.

It also requires manual execution of `sudo openssl -out /etc/nginx/ssl/dhparam.pem 4096` to create a DH-group for extra security. At the time of writing, 4096 is sufficient enough, but as time goes by, this number should be increased.
The output location can be changed, but then this must be passed to the config accordingly in the dhparam value. The charm itself will set the required permissions of the file.
### Own SSL certificates
For this the correct path for fullchain and privatekey must be provided in the config and the Nginx-user (www-data) must have read access to them.
### LetsEncrypt
After the config option setup=httpsletsencrypt and manually generating the key, setup=httpsclient can be used, with fullchain and privatekey left to its default value (empty). The charm will then set the correct permissions and uses the default letsencrypt locations of the key.

# API
The entire api is modular: extra modules will be loaded automatically if placed in the api-folder, provided they
follow the naming rules and provide the required functions.

## Error codes
The API return the following error codes:
- **400**: When the request does not contain the required data, has forbidden characters or the provided option/access-level does not exist
- **401**: When a user has no access to a certain resource
- **403**: API-key mismatch
- **404**: When a specific resource does not exists
- **405**: When a user has access to the resource, but the operation is not permitted
- **409**: When a resource already exists
- **500**: When the Sojobo, despite all its wisdom and knowledge fails

## Tengu - api
This api is used to control Juju controllers, models, applications, relations and machines. All it's calls are available under
`http://host/tengu/<call>` and are protected with basic-Authentication. The username is `admin` and the password is set with
the charm config.

## API-modules
The api is written in Flask. This allows the use of blueprints to expand the api. API-modules file names must follow
this scheme: `api_<modulename>.py`. The modulename MAY NOT contain an underscore. The module itself must have the following
inside:
```python
<MODULENAME> = Blueprint(<modulename>, __name__)


def get():
    return <MODULENAME>
```

## Controller-modules
Controller modules name must follow this scheme: `controller_<controllername>.py` and must be placed in the controller folder.
The controllername MAY NOT contain an underscore. The module itself must have the following inside:
```python
class Token(object):
    def __init__(self, url, username, password):
        self.type = <juju_controller_type>
        self.supportlxd = True
        self.url = url


def create_controller(name, region, credentials):
    ...
    return check_output(['juju', 'bootstrap', cloudname, name])


def get_supported_series():
    return ['trusty', 'xenial']
```

* A Token object, which has the controller type in lowercase, whether or not it supports lxd containers, the url of the endpoint, the required information to log into the controller (username, password, api_key, etc.). The Token objects must have the `get_credentials` and `get_cloud` functions, which return the required JuJu-styled data.
* A `create_controller(name, region, credentials)` function, which houses all the required code required to successfully bootstrap a controller of this type.
* A `get_supported_series()` function which returns a list of Ubuntu-versions this controller can deploy.

# Documentation
Documentation of the api can be found under [docs](docs).  

# Bugs
Report bugs on <a href="https://github.com/Qrama/Sojobo-api/issues">Github</a>

# Author
Mathijs Moerman <a href="mailto:mathijs.moerman@qrama.io">mathijs.moerman@qrama.io</a>

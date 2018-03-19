import sys
import os
import json
import click
import importlib
import time

import anchore_engine.configuration.localconfig
import anchore_engine.db.entities.common
from anchore_engine.db.entities.exceptions import TableNotFoundError
from anchore_engine.db.entities.exceptions import is_table_not_found
from anchore_engine.subsys import logger

import anchore_manager.cli.utils

config = {}
module = None


@click.group(name='db', short_help='DB operations')
@click.pass_obj
@click.option("--db-connect", nargs=1, help="DB connection string override.")
@click.option("--db-use-ssl", is_flag=True, help="Set if DB connection is using SSL.")
@click.option("--db-retries", nargs=1, default=1, help="If set, the tool will retry to connect to the DB the specified number of times at 5 second intervals.")
def db(ctx_config, db_connect, db_use_ssl, db_retries):
    global config, module
    config = ctx_config

    try:
        # do some DB connection/pre-checks here
        try:
            # allow override of db connect string on CLI, otherwise get DB params from anchore-engine config.yaml
            if db_connect:
                db_connect_args = {'ssl': False}
                if db_use_ssl:
                    db_connect_args['ssl'] = True
                db_params = {
                    'db_connect': db_connect,
                    'db_connect_args': db_connect_args,
                    'db_pool_size': 10,
                    'db_pool_max_overflow': 20
                }
            else:
                # config and init                                                                                                                                                
                configfile = configdir = None
                configdir = config['configdir']
                configfile = os.path.join(configdir, 'config.yaml')

                anchore_engine.configuration.localconfig.load_config(configdir=configdir, configfile=configfile)
                localconfig = anchore_engine.configuration.localconfig.get_config()

                log_level = 'INFO'
                if config['debug']:
                    log_level = 'DEBUG'
                logger.set_log_level(log_level, log_to_stdout=True)

                db_params = anchore_engine.db.entities.common.get_params(localconfig)

            print "DB Params: {}".format(json.dumps(db_params))
            rc = anchore_engine.db.entities.common.do_connect(db_params)
            print "DB connection configured: " + str(rc)

            db_connected = False
            last_db_connect_err = ""
            for i in range(0, int(db_retries)):
                print "Attempting to connect to DB..."
                try:
                    rc = anchore_engine.db.entities.common.test_connection()
                    print "DB connected: " + str(rc)
                    db_connected = True
                    break
                except Exception as err:
                    last_db_connect_err = str(err)
                    if db_retries > 1:
                        print "DB connection failed, retrying - exception: " + str(last_db_connect_err)
                        time.sleep(5)

            if not db_connected:
                raise Exception("DB connection failed - exception: " + str(last_db_connect_err))

        except Exception as err:
            raise err

    except Exception as err:
        print anchore_manager.cli.utils.format_error_output(config, 'db', {}, err)
        sys.exit(2)


@db.command(name='upgrade', short_help="Upgrade DB to version compatible with installed anchore-engine code.")
@click.option("--anchore-module", nargs=1, help="Name of anchore module to call DB upgrade routines from (default=anchore_engine)")
@click.option("--dontask", is_flag=True, help="Perform upgrade (if necessary) without prompting.")
def upgrade(anchore_module, dontask):
    """
    Run a Database Upgrade idempotently. If database is not initialized yet, but can be connected, then exit cleanly with status = 0, if no connection available then return error.
    Otherwise, upgrade from the db running version to the code version and exit.

    """
    ecode = 0

    if not anchore_module:
        module_name = "anchore_engine"
    else:
        module_name = str(anchore_module)

    try:
        try:
            print "Loading DB upgrade routines from module."
            module = importlib.import_module(module_name + ".db.entities.upgrade")
            code_versions, db_versions = module.get_versions()
        except TableNotFoundError as ex:
            print "Db not found to be initialized. No upgrade needed"
            ecode = 0
            anchore_manager.cli.utils.doexit(ecode)
        except Exception as err:
                raise Exception("Input anchore-module (" + str(module_name) + ") cannot be found/imported - exception: " + str(err))

        code_db_version = code_versions.get('db_version', None)
        running_db_version = db_versions.get('db_version', None)

        if not code_db_version:
            raise Exception("cannot code version (code_db_version={} running_db_version={})".format(code_db_version, running_db_version))
        elif code_db_version and running_db_version is None:
            print "Detected no running db version, indicating db is not initialized but is connected. No upgrade necessary. Exiting normally."
            ecode = 0
        elif code_db_version == running_db_version:
            print "Detected anchore-engine version {} and running DB version {} match, nothing to do.".format(code_db_version, running_db_version)
        else:
            print "Detected anchore-engine version {}, running DB version {}.".format(code_db_version, running_db_version)

            do_upgrade = False
            if dontask:
                do_upgrade = True
            else:
                try:
                    answer = raw_input("Performing this operation requires *all* anchore-engine services to be stopped - proceed? (y/N)")
                except:
                    answer = "n"
                if 'y' == answer.lower():
                    do_upgrade = True

            if do_upgrade:
                print "Performing upgrade."
                try:
                    # perform the upgrade logic here
                    rc = module.run_upgrade()
                    if rc:
                        print "Upgrade completed"
                    else:
                        print "No upgrade necessary. Completed."
                except Exception as err:
                    raise err
            else:
                print "Skipping upgrade."
    except Exception as err:
        print anchore_manager.cli.utils.format_error_output(config, 'dbupgrade', {}, err)
        if not ecode:
            ecode = 2

    anchore_manager.cli.utils.doexit(ecode)
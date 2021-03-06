"""
Copyright (c) 2017, 2019, Oracle and/or its affiliates. All rights reserved.
The Universal Permissive License (UPL), Version 1.0
"""

from oracle.weblogic.deploy.util import WLSDeployArchive
from oracle.weblogic.deploy.exception import BundleAwareException

from wlsdeploy.aliases.location_context import LocationContext
from wlsdeploy.aliases.validation_codes import ValidationCodes
from wlsdeploy.exception import exception_helper
from wlsdeploy.exception.expection_types import ExceptionType
from wlsdeploy.logging.platform_logger import PlatformLogger
from wlsdeploy.tool.deploy import deployer_utils
from wlsdeploy.tool.util.alias_helper import AliasHelper
from wlsdeploy.tool.util.attribute_setter import AttributeSetter
from wlsdeploy.tool.util.custom_folder_helper import CustomFolderHelper
from wlsdeploy.tool.util.wlst_helper import WlstHelper
from wlsdeploy.util import dictionary_utils
from wlsdeploy.util.model import Model
from wlsdeploy.util.weblogic_helper import WebLogicHelper
 

class Creator(object):
    """
    The base class used by the DomainCreator.
    """
    __class_name = 'Creator'

    def __init__(self, model, model_context, aliases, exception_type=ExceptionType.CREATE,
                 logger=PlatformLogger('wlsdeploy.create')):

        self.logger = logger
        self.aliases = aliases
        self._exception_type = exception_type
        self.alias_helper = AliasHelper(self.aliases, self.logger, exception_type)
        self.wlst_helper = WlstHelper(self.logger, exception_type)
        self.model = Model(model)
        self.model_context = model_context
        self.wls_helper = WebLogicHelper(self.logger)
        self.attribute_setter = AttributeSetter(self.aliases, self.logger, exception_type)
        self.custom_folder_helper = CustomFolderHelper(self.aliases, self.logger, exception_type)

        # Must be initialized by the subclass since only it has
        # the knowledge required to compute the domain name.
        self.archive_helper = None
        self.files_to_extract_from_archive = list()
        return

    def _create_named_mbeans(self, type_name, model_nodes, base_location, log_created=False):
        """
        Create the specified type of MBeans that support multiple instances in the specified location.
        :param type_name: the model folder type
        :param model_nodes: the model dictionary of the specified model folder type
        :param base_location: the base location object to use to create the MBeans
        :param log_created: whether or not to log created at INFO level, by default it is logged at the FINE level
        :raises: CreateException: if an error occurs
        """
        _method_name = '_create_named_mbeans'

        self.logger.entering(type_name, str(base_location), log_created,
                             class_name=self.__class_name, method_name=_method_name)
        if model_nodes is None or len(model_nodes) == 0 or not self._is_type_valid(base_location, type_name):
            return

        location = LocationContext(base_location).append_location(type_name)
        self._process_flattened_folder(location)

        token_name = self.alias_helper.get_name_token(location)
        create_path = self.alias_helper.get_wlst_create_path(location)
        list_path = self.alias_helper.get_wlst_list_path(location)
        existing_folder_names = self._get_existing_folders(list_path)
        for model_name in model_nodes:
            name = self.wlst_helper.get_quoted_name_for_wlst(model_name)

            if token_name is not None:
                location.add_name_token(token_name, name)

            wlst_type, wlst_name = self.alias_helper.get_wlst_mbean_type_and_name(location)
            if wlst_name not in existing_folder_names:
                if log_created:
                    self.logger.info('WLSDPLY-12100', type_name, name,
                                     class_name=self.__class_name, method_name=_method_name)
                else:
                    self.logger.fine('WLSDPLY-12100', type_name, name,
                                     class_name=self.__class_name, method_name=_method_name)
                self.wlst_helper.create_and_cd(self.alias_helper, wlst_type, wlst_name, location, create_path)
            else:
                if log_created:
                    self.logger.info('WLSDPLY-12101', type_name, name,
                                     class_name=self.__class_name, method_name=_method_name)
                else:
                    self.logger.fine('WLSDPLY-12101', type_name, name,
                                     class_name=self.__class_name, method_name=_method_name)

                attribute_path = self.alias_helper.get_wlst_attributes_path(location)
                self.wlst_helper.cd(attribute_path)

            child_nodes = dictionary_utils.get_dictionary_element(model_nodes, name)
            self.logger.finest('WLSDPLY-12111', self.alias_helper.get_model_folder_path(location),
                               self.wlst_helper.get_pwd(), class_name=self.__class_name, method_name=_method_name)
            self._set_attributes(location, child_nodes)
            self._create_subfolders(location, child_nodes)

        self.logger.exiting(class_name=self.__class_name, method_name=_method_name)
        return

    def _create_mbean(self, type_name, model_nodes, base_location, log_created=False):
        """
        Create the specified type of MBean that support a single instance in the specified location.
        :param type_name: the model folder type
        :param model_nodes: the model dictionary of the specified model folder type
        :param base_location: the base location object to use to create the MBean
        :param log_created: whether or not to log created at INFO level, by default it is logged at the FINE level
        :raises: CreateException: if an error occurs
        """
        _method_name = '_create_mbean'

        self.logger.entering(type_name, str(base_location), log_created,
                             class_name=self.__class_name, method_name=_method_name)
        if model_nodes is None or len(model_nodes) == 0 or not self._is_type_valid(base_location, type_name):
            return

        location = LocationContext(base_location).append_location(type_name)
        result, message = self.alias_helper.is_version_valid_location(location)
        if result == ValidationCodes.VERSION_INVALID:
            self.logger.warning('WLSDPLY-12123', message,
                                class_name=self.__class_name, method_name=_method_name)
            return

        create_path = self.alias_helper.get_wlst_create_path(location)
        existing_folder_names = self._get_existing_folders(create_path)

        mbean_type, mbean_name = self.alias_helper.get_wlst_mbean_type_and_name(location)

        token_name = self.alias_helper.get_name_token(location)
        if token_name is not None:
            if self.alias_helper.requires_unpredictable_single_name_handling(location):
                existing_subfolder_names = deployer_utils.get_existing_object_list(location, self.alias_helper)
                if len(existing_subfolder_names) > 0:
                    mbean_name = existing_subfolder_names[0]

            location.add_name_token(token_name, mbean_name)

        self._process_flattened_folder(location)
        if mbean_type not in existing_folder_names:
            if log_created:
                self.logger.info('WLSDPLY-12102', type_name, class_name=self.__class_name, method_name=_method_name)
            else:
                self.logger.fine('WLSDPLY-12102', type_name, class_name=self.__class_name, method_name=_method_name)

            self.wlst_helper.create_and_cd(self.alias_helper, mbean_type, mbean_name, location, create_path)
        else:
            if log_created:
                self.logger.info('WLSDPLY-20013', type_name, class_name=self.__class_name, method_name=_method_name)
            else:
                self.logger.fine('WLSDPLY-12102', type_name, class_name=self.__class_name, method_name=_method_name)

            attribute_path = self.alias_helper.get_wlst_attributes_path(location)
            self.wlst_helper.cd(attribute_path)

        self.logger.finest('WLSDPLY-12111', self.alias_helper.get_model_folder_path(location),
                           self.wlst_helper.get_pwd(), class_name=self.__class_name, method_name=_method_name)
        self._set_attributes(location, model_nodes)
        self._create_subfolders(location, model_nodes)
        self.logger.exiting(class_name=self.__class_name, method_name=_method_name)
        return

    def _create_security_provider_mbeans(self, type_name, model_nodes, base_location, log_created=False):
        """
        Create the specified security provider MBean types that support multiple instances but use an
        artificial type subfolder in the specified location.
        :param type_name: the model folder type
        :param model_nodes: the model dictionary of the specified model folder type
        :param base_location: the base location object to use to create the MBeans
        :param log_created: whether or not to log created at INFO level, by default it is logged at the FINE level
        :raises: CreateException: if an error occurs
        """
        _method_name = '_create_security_provider_mbeans'

        self.logger.entering(type_name, str(base_location), log_created,
                             class_name=self.__class_name, method_name=_method_name)
        if not self._is_type_valid(base_location, type_name):
            return

        location = LocationContext(base_location).append_location(type_name)
        self._process_flattened_folder(location)

        # For create, delete the existing nodes, and re-add in order found in model in iterative code below
        self._delete_existing_providers(location)

        if model_nodes is None or len(model_nodes) == 0:
            return

        token_name = self.alias_helper.get_name_token(location)
        create_path = self.alias_helper.get_wlst_create_path(location)
        list_path = self.alias_helper.get_wlst_list_path(location)
        existing_folder_names = self._get_existing_folders(list_path)
        known_providers = self.alias_helper.get_model_subfolder_names(location)
        allow_custom = str(self.alias_helper.is_custom_folder_allowed(location))

        for model_name in model_nodes:
            model_node = model_nodes[model_name]

            if model_node is None:
                # The node is empty so nothing to do... move to the next named node.
                continue

            if len(model_node) != 1:
                # there should be exactly one type folder under the name folder
                ex = exception_helper.create_exception(self._exception_type, 'WLSDPLY-12117', type_name, model_name,
                                                       len(model_node))
                self.logger.throwing(ex, class_name=self.__class_name, method_name=_method_name)
                raise ex

            model_type_subfolder_name = list(model_node.keys())[0]
            child_nodes = dictionary_utils.get_dictionary_element(model_node, model_type_subfolder_name)

            # custom providers require special processing, they are not described in alias framework
            if allow_custom and (model_type_subfolder_name not in known_providers):
                self.custom_folder_helper.update_security_folder(base_location, type_name, model_type_subfolder_name,
                                                                 model_name, child_nodes)
                continue

            # for a known provider, process using aliases
            prov_location = LocationContext(location)
            name = self.wlst_helper.get_quoted_name_for_wlst(model_name)
            if token_name is not None:
                prov_location.add_name_token(token_name, name)

            wlst_base_provider_type, wlst_name = self.alias_helper.get_wlst_mbean_type_and_name(prov_location)

            prov_location.append_location(model_type_subfolder_name)
            wlst_type = self.alias_helper.get_wlst_mbean_type(prov_location)

            if wlst_name not in existing_folder_names:
                if log_created:
                    self.logger.info('WLSDPLY-12118', type_name, model_type_subfolder_name, name, create_path,
                                     class_name=self.__class_name, method_name=_method_name)
                else:
                    self.logger.fine('WLSDPLY-12118', type_name, model_type_subfolder_name, name, create_path,
                                     class_name=self.__class_name, method_name=_method_name)
                self.wlst_helper.cd(create_path)
                self.wlst_helper.create(wlst_name, wlst_type, wlst_base_provider_type)
            else:
                if log_created:
                    self.logger.info('WLSDPLY-12119', type_name, model_type_subfolder_name, name, create_path,
                                     class_name=self.__class_name, method_name=_method_name)
                else:
                    self.logger.fine('WLSDPLY-12119', type_name, model_type_subfolder_name, name, create_path,
                                     class_name=self.__class_name, method_name=_method_name)

            attribute_path = self.alias_helper.get_wlst_attributes_path(prov_location)
            self.wlst_helper.cd(attribute_path)

            self.logger.finest('WLSDPLY-12111', self.alias_helper.get_model_folder_path(prov_location),
                               self.wlst_helper.get_pwd(), class_name=self.__class_name, method_name=_method_name)
            self._set_attributes(prov_location, child_nodes)
            self._create_subfolders(prov_location, child_nodes)

        self.logger.exiting(class_name=self.__class_name, method_name=_method_name)
        return

    def _set_attributes(self, location, model_nodes):
        """
        Set the attributes for the MBean at the specified location.
        :param location: the location
        :param model_nodes: the model dictionary
        :raises: CreateException: if an error occurs
        """
        _method_name = '_set_attributes'

        model_attribute_names = self.alias_helper.get_model_attribute_names_and_types(location)
        password_attribute_names = self.alias_helper.get_model_password_type_attribute_names(location)
        set_method_map = self.alias_helper.get_model_mbean_set_method_attribute_names_and_types(location)
        uses_path_tokens_attribute_names = self.alias_helper.get_model_uses_path_tokens_attribute_names(location)
        model_folder_path = self.alias_helper.get_model_folder_path(location)
        pwd = self.wlst_helper.get_pwd()

        for key, value in model_nodes.iteritems():
            if key in model_attribute_names:
                if key in set_method_map:
                    self.logger.finest('WLSDPLY-12112', key, pwd, model_folder_path,
                                       class_name=self.__class_name, method_name=_method_name)
                    self._set_mbean_attribute(location, key, value, set_method_map)
                elif key in password_attribute_names:
                    self.logger.finest('WLSDPLY-12113', key, pwd, model_folder_path,
                                       class_name=self.__class_name, method_name=_method_name)
                    self._set_attribute(location, key, value, uses_path_tokens_attribute_names, masked=True)
                else:
                    self.logger.finest('WLSDPLY-12113', key, pwd, model_folder_path,
                                       class_name=self.__class_name, method_name=_method_name)
                    self._set_attribute(location, key, value, uses_path_tokens_attribute_names)
        return

    def _set_mbean_attribute(self, location, model_key, model_value, set_method_map):
        """
        Set the attributes for the MBean that require an MBean value to set at the specified location.
        :param location: the location
        :param model_key: the model attribute name
        :param model_value: the model attribute value
        :param set_method_map: the set method map that maps the attribute names requiring MBean
                               values to the attribute setter method name
        :raises: CreateException: if an error occurs
        """
        _method_name = '_set_mbean_attribute'

        set_method_info = dictionary_utils.get_dictionary_element(set_method_map, model_key)
        set_method_name = dictionary_utils.get_element(set_method_info, 'set_method')

        if set_method_name is not None:
            try:
                self.logger.finest('WLSDPLY-12114', model_key, model_value, set_method_name,
                                   class_name=self.__class_name, method_name=_method_name)
                set_method = getattr(self.attribute_setter, set_method_name)
                set_method(location, model_key, model_value, None)
            except AttributeError, ae:
                ex = exception_helper.create_create_exception('WLSDPLY-12104', set_method_name, model_key,
                                                              self.alias_helper.get_model_folder_path(location),
                                                              error=ae)
                self.logger.throwing(ex, class_name=self.__class_name, method_name=_method_name)
                raise ex
        else:
            ex = exception_helper.create_create_exception('WLSDPLY-12105', model_key,
                                                          self.alias_helper.get_model_folder_path(location))
            self.logger.throwing(ex, class_name=self.__class_name, method_name=_method_name)
            raise ex
        return

    def _set_attribute(self, location, model_name, model_value, uses_path_tokens_names, masked=False):
        """
        Set the specified attribute at the specified location to the specified value.
        :param location: the location
        :param model_name: the model attribute name
        :param model_value: the model attribute value
        :param: uses_path_token_names: the list of model attribute names that use file system path tokens
        :param masked: whether or not to mask the attribute value in the log
        :raises: CreateException: if an error occurs
        """
        _method_name = '_set_attribute'

        if model_name in uses_path_tokens_names and WLSDeployArchive.isPathIntoArchive(model_value):
            if self.archive_helper is not None:
                if self.archive_helper.contains_file(model_value):
                    #
                    # We cannot extract the files until the domain directory exists
                    # so add them to the list so that they can be extracted after
                    # domain creation completes.
                    #
                    self.files_to_extract_from_archive.append(model_value)
                else:
                    path = self.alias_helper.get_model_folder_path(location)
                    archive_file_name = self.model_context.get_archive_file_name
                    ex = exception_helper.create_create_exception('WLSDPLY-12121', model_name, path,
                                                                  model_value, archive_file_name)
                    self.logger.throwing(ex, class_name=self.__class_name, method_name=_method_name)
                    raise ex
            else:
                path = self.alias_helper.get_model_folder_path(location)
                ex = exception_helper.create_create_exception('WLSDPLY-12122', model_name, path, model_value)
                self.logger.throwing(ex, class_name=self.__class_name, method_name=_method_name)
                raise ex

        wlst_name, wlst_value = self.alias_helper.get_wlst_attribute_name_and_value(location, model_name, model_value)

        if wlst_name is None:
            self.logger.info('WLSDPLY-12106', model_name, self.alias_helper.get_model_folder_path(location),
                             class_name=self.__class_name, method_name=_method_name)
        elif wlst_value is None:
            logged_value = model_value
            if masked:
                logged_value = '<masked>'
            self.logger.info('WLSDPLY-12107', model_name, logged_value,
                             self.alias_helper.get_model_folder_path(location),
                             class_name=self.__class_name, method_name=_method_name)
        else:
            logged_value = wlst_value
            if masked:
                logged_value = '<masked>'
            self.logger.finest('WLSDPLY-12115', wlst_name, logged_value,
                               class_name=self.__class_name, method_name=_method_name)
            self.wlst_helper.set(wlst_name, wlst_value, masked=masked)
        return

    def _create_subfolders(self, location, model_nodes):
        """
        Create the child MBean folders at the specified location.
        :param location: the location
        :param model_nodes: the model dictionary
        :raises: CreateException: if an error occurs
        """
        _method_name = '_create_subfolders'

        self.logger.entering(location.get_folder_path(), class_name=self.__class_name, method_name=_method_name)
        model_subfolder_names = self.alias_helper.get_model_subfolder_names(location)
        for key in model_nodes:
            if key in model_subfolder_names:
                subfolder_nodes = model_nodes[key]
                sub_location = LocationContext(location).append_location(key)
                # both create and update are merge to model so will process a subfolder with an empty node
                if self.alias_helper.requires_artificial_type_subfolder_handling(sub_location):
                    self.logger.finest('WLSDPLY-12116', key, str(sub_location), subfolder_nodes,
                                       class_name=self.__class_name, method_name=_method_name)
                    self._create_security_provider_mbeans(key, subfolder_nodes, location, True)
                elif len(subfolder_nodes) != 0:
                    if self.alias_helper.supports_multiple_mbean_instances(sub_location):
                        self.logger.finest('WLSDPLY-12109', key, str(sub_location), subfolder_nodes,
                                           class_name=self.__class_name, method_name=_method_name)
                        self._create_named_mbeans(key, subfolder_nodes, location)
                    elif self.alias_helper.is_artificial_type_folder(sub_location):
                        ex = exception_helper.create_create_exception('WLSDPLY-12120', str(sub_location),
                                                                      key, str(location))
                        self.logger.throwing(ex, class_name=self.__class_name, method_name=_method_name)
                        raise ex
                    else:
                        self.logger.finest('WLSDPLY-12110', key, str(sub_location), subfolder_nodes,
                                           class_name=self.__class_name, method_name=_method_name)
                        self._create_mbean(key, subfolder_nodes, location)

        self.logger.exiting(class_name=self.__class_name, method_name=_method_name)
        return

    def _is_type_valid(self, location, type_name):
        """
        Verify that the specified location in valid for the current WLS version.
        A warning is logged if the location is not valid.
        :param location: the location to be checked
        :param type_name: the type location to be checked
        :return: True if the location is valid, False otherwise
        :raises: CreateException: if an error occurs
        """
        _method_name = '_check_location'

        code, message = self.alias_helper.is_valid_model_folder_name(location, type_name)
        result = False
        if code == ValidationCodes.VALID:
            result = True
        elif code == ValidationCodes.VERSION_INVALID:
            path = self._format_model_path(location, type_name)
            self.logger.warning('WLSDPLY-12108', path, message,
                                class_name=self.__class_name, method_name=_method_name)
        #
        return result

    def _process_flattened_folder(self, location):
        """
        Create the flattened folder at the specified location if one exists.
        :param location: the location
        :raises: CreateException: if an error occurs
        """
        if self.alias_helper.is_flattened_folder(location):
            create_path = self.alias_helper.get_wlst_flattened_folder_create_path(location)
            mbean_type = self.alias_helper.get_wlst_flattened_mbean_type(location)
            mbean_name = self.alias_helper.get_wlst_flattened_mbean_name(location)
            existing_folders = self._get_existing_folders(create_path)
            if mbean_type not in existing_folders:
                self.wlst_helper.create(mbean_name, mbean_type)
        return

    def _delete_existing_providers(self, location):
        """
        The security realms providers in the model are processed as merge to the model. Each realm provider
        section must be complete and true to the resulting domain. Any existing provider not found in the
        model will be removed, and any provider in the model but not in the domain will be added. The resulting
        provider list will be ordered as listed in the model. If the provider type (i.e. AuthenticationProvider)
        is not in the model, it is assumed no configuration or ordering is needed, and the provider is skipped.
        If the provider type is in the model, but there is no MBean entry under the provider, then it is 
        assumed that all providers for that provider type must be removed.

        For create, the default realm and default providers have been added by the weblogic base template and any
        extension templates. They have default values. These providers will be removed from the domain. During
        the normal iteration through the provider list, the providers, if in the model, will be re-added in model
        order. Any attributes in the model that are not the default value are then applied to the the new provider.

        By deleting all providers and re-adding from the model, we are both merging to the model and ordering the
        providers. In offline wlst, the set<providertype>Providers(<provider_object_list>, which reorders existing
        providers, does not work. Deleting the providers and re-adding also has the added benefit of fixing the 11g
        problem where the providers have no name. They are returned with the name 'Provider'. In the authentication
        provider, there are two default providers, and just setting the name does not work. When we re-add we re-add
        with the correct name. And the DefaultAuthenticationProvider successfully re-adds with the correct default
        identity asserter.

        This release also supports updating the security configuration realms in both offline and online mode. This
        release requires a complete list of providers as described in the first paragraph.

        :param location: current context of the location pointing at the provider mbean
        """
        _method_name = '_delete_existing_providers'
        self.logger.entering(location.get_folder_path(), class_name=self.__class_name, method_name=_method_name)

        list_path = self.alias_helper.get_wlst_list_path(location)
        existing_folder_names = self._get_existing_folders(list_path)
        wlst_base_provider_type = self.alias_helper.get_wlst_mbean_type(location)
        if len(existing_folder_names) == 0:
            self.logger.finer('WLSDPLY-12136', wlst_base_provider_type, list_path, class_name=self.__class_name,
                              method_name=_method_name)
        else:
            create_path = self.alias_helper.get_wlst_create_path(location)
            self.wlst_helper.cd(create_path)
            for existing_folder_name in existing_folder_names:
                try:
                    self.logger.info('WLSDPLY-12135', existing_folder_name, wlst_base_provider_type, create_path,
                                     class_name=self.__class_name, method_name=_method_name)
                    self.wlst_helper.delete(existing_folder_name, wlst_base_provider_type)
                except BundleAwareException, bae:
                    ex = exception_helper.create_exception(self._exception_type, 'WLSDPLY-12134', existing_folder_name,
                                                           self.wls_helper.get_weblogic_version(),
                                                           wlst_base_provider_type, bae.getLocalizedMessage(),
                                                           error=bae)
                    self.logger.throwing(ex, class_name=self.__class_name, method_name=_method_name)
                    raise ex

        self.logger.exiting(class_name=self.__class_name, method_name=_method_name)
        return

    def _get_existing_folders(self, wlst_path):
        """
        Get the list of existing folders at the specified WLST path.
        :param wlst_path: the WLST path
        :return: the list of existing folders, or an empty list if none exist
        """
        return self.wlst_helper.get_existing_object_list(wlst_path)

    def _format_model_path(self, location, name):
        """
        Get the model path of the specified name.
        :param location: the location
        :param name: the name to append to the model folder path
        :return: the path of the specified name
        """
        path = self.alias_helper.get_model_folder_path(location)
        if not path.endswith('/'):
            path += '/'
        path += name
        return path

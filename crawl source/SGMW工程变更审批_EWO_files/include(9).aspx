
/** search_container.js **/
// © Copyright by Aras Corporation, 2004-2012.

// Must be initialized on the page search been added.
var searchContainer = null;
var currentSearchMode = null;
var fromImplementationItemTypeName = undefined;

function SearchContainer(itemTypeName, toolbarInfo, gridInfo, menuInfo, searchLocation, searchPlaceholder, requiredProperties, paginationInfo, searchToolbar) {
	/// <summary>
	///   Mission of the SearchContainer class is to simplify adding search mechanism to any page in the Innovator.
	///   To use search at the page, a new instance of the class must be created.
	///   Class operates by Aras.Client.JS.SearchMode objects.
	/// </summary>
	/// <example>
	///   <code language="html">
	///<![CDATA[<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 4.01//EN" "http://www.w3.org/TR/html4/strict.dtd">
	///<html>
	///<head>
	///  <title></title>
	///  <link rel="stylesheet" type="text/css" href="../styles/default.css" />
	///
	///  <script type="text/javascript" src="../javascript/include.aspx?classes=ScriptSet6"></script>
	///
	///</head>
	///<body>
	///
	///  <script type="text/javascript">
	///    onload = function onload_handler()
	///    {
	///      searchContainer = new SearchContainer(itemTypeName, toolbar, grid, "My Search Location", searchPlaceholder);
	///      searchContainer.initSearchModesInToolbar();
	///      searchContainer.initSavedSearchesInToolbar();
	///      searchContainer.showAutoSavedSearchMode();
	///    }
	///  </script>
	///
	///  <table id="main_table" border="0" style="width: 100%; height: 100%; table-layout: fixed;"
	///    cellspacing="0" cellpadding="0">
	///    <tr style="height: 28px;">
	///      <td>
	///        <object id="toolbar">
	///        </object>
	///      </td>
	///    </tr>
	///    <tr id="searchPlaceholder" style="display: none; height: 0px;">
	///    </tr>
	///    <!-- IE has bug not allowing to set rows height in % when standards turned on. //
	///    tr_IE_fix_bug_with_height - special style from styles\default.css that helps to
	///    solve this problem.
	///    -->
	///    <tr class="tr_IE_fix_bug_with_height">
	///      <td>
	///        <object id="grid">
	///        </object>
	///      </td>
	///    </tr>
	///  </table>
	///</body>
	///</html>]]>
	/// </code>
	/// </example>
	/// <summary locid="M:J#Aras.Client.JS.SearchContainer.#ctor">
	/// This is summary for constructor.
	/// </summary>
	/// <param locid="M:J#Aras.Client.JS.InnovatorClient.#ctor" name="itemTypeName" type="string" mayBeNull="true">
	///   Name of the ItemType which items you want to search for.
	/// </param>
	/// <param locid="M:J#Aras.Client.JS.InnovatorClient.#ctor" name="toolbar" mayBeNull="true" type="BaseComponent">
	///   Toolbar that will be used to operate by search.
	///   Instance of the Aras.Client.Controls.Toolbar. Must be loaded before passing into SearchContainer.
	/// </param>
	/// <param locid="M:J#Aras.Client.JS.InnovatorClient.#ctor" name="grid" mayBeNull="true" type="BaseComponent">
	///   Grid to display search results. Also can be used by search mode for generating query (like "Simple" search mode do).
	///   Instance of the Aras.Client.Controls.GridContainer. Must be loaded before passing into SearchContainer.
	/// </param>
	/// <param locid="M:J#Aras.Client.JS.InnovatorClient.#ctor" name="menu" mayBeNull="true" type="BaseComponent">
	///   Menu to operate by search.
	///   Instance of the Aras.Client.Controls.MainMenu. Must be loaded before passing into SearchContainer.
	/// </param>
	/// <param locid="M:J#Aras.Client.JS.InnovatorClient.#ctor" name="searchLocation" type="string" mayBeNull="false">
	///   Name of the place where search will be used.
	///   This parameter has sence because search behaviour can be different in different search locations.
	///   See "SearchLocations" list for all possible search location values.
	/// </param>
	/// <param locid="M:J#Aras.Client.JS.InnovatorClient.#ctor" name="searchPlaceholder" type="Object" mayBeNull="false">
	///   Object at the page which will contain search modes.
	/// </param>
	/// <param locid="M:J#Aras.Client.JS.InnovatorClient.#ctor" name="requiredProperties" type="Object" mayBeNull="true">
	///   Name:Value collection of properties that must be applied to every quiery.
	/// </param>

	if (arguments.length == 0) {
		return;
	}

	this.itemTypeName = itemTypeName;

	function getObject(info) { return info && info.object && info.dojoOfObject ? info.object : info; }
	function getDojo(info) { return info && info.object && info.dojoOfObject ? info.dojoOfObject : window.dojo; }

	this.grid = getObject(gridInfo);
	this._gridDojo = getDojo(gridInfo);

	this.toolbar = getObject(toolbarInfo);
	this._toolbarDojo = getDojo(toolbarInfo);

	this.searchToolbar = searchToolbar;

	this.pagination = paginationInfo;
	if (this.pagination) {
		this.pagination.addEventListener('runSearch', (function() {
			this.runSearch();
		}).bind(this));
	}

	var grid = this.grid,
		toolbar = this.toolbar;

	this.searchLocation = searchLocation;
	this.searchPlaceholder = searchPlaceholder;
	this.requiredProperties = requiredProperties;
	this.defaultSearchProperties = new Object();
	this.redlineController = null;
	var tmpXmlDocument = aras.createXMLDocument();
	this.searchParameterizedHelper = new SearchParameterizedHelper(tmpXmlDocument);
	this.itemTypeCache = {};

	if (this.searchPlaceholder) {
		var newChildElementMustBeCreated = true;
		this.searchPlaceholderCell = null;
		if (this.searchPlaceholder.childNodes.length > 0) {
			for (var i = 0; i < this.searchPlaceholder.childNodes.length; i++) {
				if (this.searchPlaceholder.childNodes[i].id == 'searchPlaceholderCell') {
					this.searchPlaceholderCell = this.searchPlaceholder.childNodes[i];
					newChildElementMustBeCreated = false;
					break;
				}
			}
		}

		if (newChildElementMustBeCreated) {
			var searchPlaceholderNodeName = this.searchPlaceholder.nodeName.toUpperCase();
			if ('TR' == searchPlaceholderNodeName || 'DIV' == searchPlaceholderNodeName) {
				this.searchPlaceholderCell = this.searchPlaceholder.appendChild(this.searchPlaceholder.ownerDocument.createElement(searchPlaceholderNodeName == 'TR' ? 'td' : 'div'));
				this.searchPlaceholderCell.id = 'searchPlaceholderCell';
			} else {
				this.searchPlaceholderCell = searchPlaceholder;
			}
		}
	}

	// ************************************* Private SearchContainer members *************************************
	var getCriteriaFromAutoSavedSearch = false;
	var onSearchDialogUpdatesQueryExplicitly = false;

	// Variable will store last selected value in SavedSearch comboBox.
	// If user select new savedSearch and it's not compatible with current searchMode, user can cancel switching.
	// Variable will be used to return previously selected search.

	var worldIdentityId = null;
	const searchCollection = {};
	var currentSearchFrame = null;

	function getSearchModeInstance(searchItemId, searchModeId, searchContainer) {
		if (!searchCollection[searchItemId]) {
			const searchModeItem = aras.getSearchMode(searchModeId);
			const newSearchModeName = aras.getItemProperty(searchModeItem, 'name');
			const newSearchModeLabel = aras.getItemProperty(searchModeItem, 'label');

			dojo.eval(aras.getItemProperty(searchModeItem, 'search_handler'));
			const newSearchMode = new window[newSearchModeName](searchContainer, aras);
			newSearchMode.id = searchModeId;
			newSearchMode.name = newSearchModeName;
			newSearchMode.label = newSearchModeLabel || newSearchModeName;
			searchCollection[searchItemId] = newSearchMode;
		}
		return {id: searchItemId, searchMode: searchCollection[searchItemId]};
	}

	function getWorldIdentityId() {
		return 'A73B655731924CD0B027E4F4D5FCC0A9';
	}

	function toolbarOnChangeHandler(tbId) {
		var tbItemId = tbId.getId();
		if (tbItemId == 'search_mode' || tbItemId == 'saved_search') {
			var selected_item = tbId.getSelectedItem();
			if (tbItemId == 'search_mode' && tbId.getEnabled()) {
				searchContainer.showSearchMode(selected_item);
			} else {
				searchContainer._onSavedSearchChange(selected_item);
			}

			searchContainer._updateSearchMenu();
			if (window.onresize) {
				window.onresize();
			}

			if (typeof(searchContainer.grid.RefreshHeight) == 'function') {
				searchContainer.grid.RefreshHeight();
			}

		}
	}

	function toolbarOnClickHandler(tbId) {
		const tbItemId = tbId.getId();
		if (tbItemId === 'search') {
			if (!currentSearchMode.setPageNumber(1)) {
				return;
			}
			currentSearchMode.removeCacheItem('itemmax');
			currentSearchMode.removeCacheItem('pagemax');
			currentSearchMode.removeCacheItem('itemsWithNoAccessCount');
			currentSearchMode.removeCacheItem('criteriesHash');
			searchContainer.runSearch();

		} else if (tbItemId === 'newsearch') {
			if (searchContainer) {
				searchContainer.defaultSearchProperties = new Object();
			}
			currentSearchMode.removeCacheItem('itemmax');
			currentSearchMode.removeCacheItem('pagemax');
			currentSearchMode.removeCacheItem('itemsWithNoAccessCount');
			currentSearchMode.removeCacheItem('criteriesHash');
			currentSearchMode.clearSearchCriteria();

		} else if (tbItemId === 'stop_search') {
			stopSearch();

		} else if (tbItemId === 'add_criteria' && currentSearchMode.newCriteriaRow) {
			currentSearchMode.newCriteriaRow();

		} else if (tbItemId === 'select_all') {
			doSelectAll();

		}
	}

	function showIncompatibleAMLPromptDialog(searchModeLabel) {
		const win = aras.getMostTopWindowWithAras(window);
		const dialogMessage = aras.getResource('', 'search_container.aml_is_not_compatible_with_new_search_mode', searchModeLabel);
		return win.ArasModules.Dialog.confirm(dialogMessage, {
			title: aras.getResource('', 'search.warning'),
 			additionalButton: {
 				text: aras.getResource('', 'common.clear_all'),
 				actionName: 'clear'
 			}
		});
	}

	function getSavedSearch(savedSearchId) {
		var savedSearch = null;

		var savedSearches = aras.getSavedSearches(itemTypeName, searchLocation);
		if (savedSearches && savedSearches.length > 0) {
			for (var i = 0; i < savedSearches.length; i++) {
				if (aras.getItemProperty(savedSearches[i], 'id') == savedSearchId) {
					savedSearch = savedSearches[i];
					break;
				}
			}
		}

		return savedSearch;
	}

	function gridSortEventHandler(columnIdx, asc, ctrl) {
		if (aras.getVariable('SortPages') !== 'true') {
			return false;
		}
		var orderByValue = this.grid_Experimental
			.getSortProps()
			.filter(function(sortProperty) {
				return sortProperty.attribute !== '_newRowMarker' && sortProperty.attribute !== 'uniqueId';
			})
			.map(function(sortProperty) {
				var columnIndex = this.grid_Experimental.parentContainer.getColumnIndex(sortProperty.attribute);
				var itemTypePropertyNode = searchContainer.getPropertyDefinitionByColumnIndex(columnIndex);
				var sortDirection = sortProperty.descending ? 'DESC' : 'ASC';

				return {
					name: aras.getItemProperty(itemTypePropertyNode, 'name'),
					sortDirection: sortDirection
				};
			}, this)
			.map(function(property) {
				return property.name + ' ' + property.sortDirection;
			})
			.join(', ');
		currentSearchMode.setOrderBy(orderByValue);
		searchContainer.runSearch();

		return true;
	}

	function notifyCuiLayout(eventType) {
		if (window.layout) {
			window.layout.observer.notify(eventType);
		}
	}
	// ************************************* Private SearchContainer members *************************************

	// ************************************* Privileged SearchContainer members *************************************
	this._applyRequiredProperties = function(searchAml) {
		if (!this.requiredProperties) {
			return searchAml;
		}

		var query = aras.newQryItem(this.itemTypeName);
		query.loadXML(searchAml);

		var useWildcards = (aras.getPreferenceItemProperty('Core_GlobalLayout', null, 'core_use_wildcards') == 'true');
		for (var propName in this.requiredProperties) {
			var criteria = this.requiredProperties[propName];
			query.setCriteria(propName, criteria, ((useWildcards && /[%|*]/.test(criteria)) ? 'like' : 'eq'));
		}

		return query.dom.xml;
	};

	this._applyDefaultSearchProperties = function(searchAml) {
		if (!this.defaultSearchProperties) {
			return searchAml;
		}

		var currItemType = this._getCurrentItemType();
		if (!currItemType) {
			return searchAml;
		}

		var query = aras.newQryItem(this.itemTypeName);
		query.loadXML(searchAml);

		var useWildcards = (aras.getPreferenceItemProperty('Core_GlobalLayout', null, 'core_use_wildcards') == 'true');

		for (var propName in this.defaultSearchProperties) {
			var propNd = null;
			var propDT = '';
			var propDS = '';
			if (currItemType) {
				propNd = currItemType.selectSingleNode('Relationships/Item[@type=\'Property\' and name=\'' + propName + '\']');
			}

			if (propNd) {
				propDT = aras.getItemProperty(propNd, 'data_type');
				propDS = aras.getItemPropertyAttribute(propNd, 'data_source', 'name');
			}

			var criteria = this.defaultSearchProperties[propName];
			var condition = ((useWildcards && /[%|*]/.test(criteria)) ? 'like' : 'eq');

			var criteriaProp = query.item.selectSingleNode(propName);
			if (!criteriaProp || userMethodColumnCfgs[propName].isFilterFixed) {
				if ('item' == propDT) {
					query.setPropertyCriteria(propName, 'keyed_name', criteria, condition, propDS);
				} else {
					query.setCriteria(propName, criteria, condition);
				}
			}
		}

		return query.dom.xml;
	};

	this._saveSearch = function() {
		/// <summary>
		/// Allows to save current search criteria into SavedSearch.
		/// </summary>
		/// <remarks>
		/// There are two types of SavedSearches : shared (created by administrators and available to everybody) and identity-based(available to a particular identity).
		/// Administrator are able to create\modify all searches in the system;
		/// all other users are able to create\modify only searches which are assigned to their identity with is_alias=true.
		/// This method shows dialog allowing to input label for SavedSearch and specify type of it - shared or identity-based.
		/// </remarks>
		var formNd = aras.getItemByName('Form', 'SavedSearch Save Dialog', 0);
		if (formNd) {
			var param = new Object();
			param.aras = aras;
			param.title = 'Save new SavedSearch';
			param.formId = formNd.getAttribute('id');
			param.item = this._createNewSavedSearch(false, currentSearchMode.getAml(), currentSearchMode.id);

			if (this.toolbar && this.toolbar.isButtonVisible('saved_search')) {
				var savedSearchItem = getSavedSearch(this.toolbar.getItem('saved_search').getSelectedItem());
				if (savedSearchItem && '1' != aras.getItemProperty(savedSearchItem, 'auto_saved')) {
					var savedSearchWithLabels = aras.getItemFromServer('SavedSearch', savedSearchItem.getAttribute('id'), 'label', false, '*').node;
					if (savedSearchWithLabels) {
						var languages = aras.getLanguagesResultNd().selectNodes('Item[@type=\'Language\']');
						for (var i = 0, j = languages.length; i < j; i++) {
							var languageCode = aras.getItemProperty(languages[i], 'code');
							var searchLabel = aras.getNodeTranslationElement(savedSearchWithLabels, 'label', languageCode);
							aras.setNodeTranslationElement(param.item.node, 'label', searchLabel, languageCode);
						}

						param.item.setProperty('owned_by_id', aras.getItemProperty(savedSearchItem, 'owned_by_id'));
						param.item.setProperty('show_on_toc', aras.getItemProperty(savedSearchItem, 'show_on_toc'));
					}
				}
			}

			var width = aras.getItemProperty(formNd, 'width') || 500;
			var height = aras.getItemProperty(formNd, 'height') || 150;
			param.dialogWidth = width;
			param.dialogHeight = height;
			param.content = 'ShowFormAsADialog.html';
			const win = aras.getMostTopWindowWithAras(window);
			win.ArasModules.Dialog.show('iframe', param).promise.then(
				function(resultItem) {
					if (resultItem) {
						const savedSearchId = aras.getItemProperty(resultItem, 'id');
						const mustViewById = aras.getItemProperty(resultItem, 'owned_by_id');
						const aml = '<AML>' +
							resultItem.xml +
							'<Item type="Favorite" action="add">' +
								'<category>Search</category>' +
								'<classification>Favorites</classification>' +
								'<context_type>' + this.itemTypeName +'</context_type>' +
								'<owned_by_id>' + aras.getIsAliasIdentityIDForLoggedUser() + '</owned_by_id>' +
								'<label>' + aras.getItemProperty(resultItem, 'label') + '</label>' +
								'<name>' + (aras.getItemProperty(resultItem, 'label') || '') + '</name>' +
								'<quick_access_flag>' + aras.getItemProperty(resultItem, 'show_on_toc') + '</quick_access_flag>' +
								'<additional_data>' + JSON.stringify({id: savedSearchId}) + '</additional_data>' +
								(mustViewById !== aras.getIsAliasIdentityIDForLoggedUser() ?
									'<Relationships>' +
										'<Item type="FavoriteMustViewBy" action="add">' +
											'<related_id>' + mustViewById +'</related_id>' +
										'</Item>' +
									'</Relationships>' :
									''
								) +
							'</Item>' +
						'</AML>';
						var res = aras.soapSend('ApplyAML', aml);
						if (res.getFaultCode() != 0) {
							aras.AlertError(res);
							return;
						}

						this._updateAutoSavedSearch();
						aras.MetadataCache.RemoveItemById('56E808C94358462EAA90870A2B81AD96');
						if (window.layout) {
							const favoriteItemNode = ArasModules.xml.selectSingleNode(res.getResult(), 'Item[@type="Favorite"]');
							const favoriteItem = aras.newIOMItem();
							favoriteItem.node = favoriteItemNode;
							this.applyFavoriteSearch(favoriteItem);
						} else {
							this._initSavedSearchesInToolbar();
						}
					}
				}.bind(this)
			);
		}
	};

	this._deleteSearch = function() {
		/// <summary>
		/// Deletes current SavedSearch displayed by SearchContainer.
		/// </summary>
		/// <remarks>
		/// Administrator are able to delete all searches in the system;
		/// all other users are able to delete only searches which are assigned to their identity with is_alias=true.
		/// </remarks>
		if (!this.currentFavoriteItem) {
			return;
		}

		const selected_item_label = this.currentFavoriteItem.getProperty('label') || aras.getResource('', 'common.no_label');
		var savedSearchItemType = aras.getItemTypeForClient('SavedSearch').node;
		var savedSearchLabel = aras.getItemProperty(savedSearchItemType, 'label');

		var res = aras.confirm(aras.getResource('', 'itemsgrid.delete_confirmation', savedSearchLabel, selected_item_label));
		if (res) {
			// If user clicks “Yes” on it the currently selected saved search is deleted,
			// the drop-down list of saved searches is updated; search criteria (if shown in UI) is cleared
			// and the drop-down list shows that no saved search is currently selected (i.e. displays empty string).
			const favoriteId = this.currentFavoriteItem.getProperty('id');
			const additionalData = this.currentFavoriteItem.getProperty('additional_data');
			const savedSearchId = JSON.parse(additionalData).id;
			const aml = '<AML>' +
				'<Item type="Favorite" action="delete" id="' + favoriteId +'" />' +
				'<Item type="SavedSearch" action="delete" id="' + savedSearchId +'" />' +
			'</AML>';
			const result = aras.soapSend('ApplyAML', aml);
			if (result.getFaultCode() != 0) {
				aras.AlertError(result);
				return;
			}

			aras.MetadataCache.RemoveItemById(savedSearchId);

			currentSearchMode.clearSearchCriteria();
			if (window.layout) {
				this.applyFavoriteSearch(null);
			} else {
				this._initSavedSearchesInToolbar();
			}
			this._initSavedSearchesInToolbar();
			this._updateAutoSavedSearch();
			this._updateSaveDeleteMenu();
		}
	};

	this._initSearchModesInToolbar = function() {
		/// <summary>
		/// Gets available SearchModes and populates choice with id="search_mode" in search toolbar.
		/// </summary>
		if (!this.toolbar) {
			return;
		}

		var searchModeChoice = this.toolbar.getItem('search_mode');
		if (!searchModeChoice) {
			return;
		}

		searchModeChoice.removeAll();

		var searchModes = aras.getSearchModes();
		if (searchModes) {
			for (var i = 0; i < searchModes.length; i++) {
				var searchModeNd = searchModes[i];
				var modeId = aras.getItemProperty(searchModeNd, 'id');
				var modeLabel = aras.getItemProperty(searchModeNd, 'label');
				if (!modeLabel) {
					modeLabel = aras.getItemProperty(searchModeNd, 'name');
				}

				searchModeChoice.Add(modeId, modeLabel);
			}
		}
	};

	this._initSavedSearchesInToolbar = function() {
		/// <summary>
		/// Gets available savedSearches and populates choice with id="saved_search" in search toolbar.
		/// </summary>
		/// <remarks>
		///   If only auto_saved SavedSearch available, comboBox will be hidden.
		///   If more that one SavedSearch available, auto_saved SavedSearch will be selected by default.
		/// </remarks>
		if (!this.toolbar) {
			return;
		}

		var savedSearchChoice = this.toolbar.getItem('saved_search');
		if (!savedSearchChoice) {
			return;
		}

		savedSearchChoice.removeAll();
		var savedSearches = aras.getSavedSearches(this.itemTypeName, this.searchLocation);

		if ('Search Dialog' == this.searchLocation) {
			var savedSearchesFromMainGrid = aras.getSavedSearches(this.itemTypeName, 'Main Grid');
			if (savedSearchesFromMainGrid && savedSearchesFromMainGrid.length > 0) {
				if (savedSearches) {
					for (var i = 0; i < savedSearchesFromMainGrid.length; i++) {
						if (aras.getItemProperty(savedSearchesFromMainGrid[i], 'auto_saved') != '1') {
							savedSearches.push(savedSearchesFromMainGrid[i]);
						}
					}
				}
			}
		}

		if (!savedSearches || savedSearches.length == 0 || (savedSearches.length == 1 && aras.getItemProperty(savedSearches[0], 'auto_saved') == '1')) {
			this.toolbar.hideItem('saved_search');
			delete this.currentSavedSearchId;
			notifyCuiLayout('SelectFavorite');
			return;
		}

		var sharedSearches = new Array();
		var identityBasedSearches = new Array();
		var autoSavedSearch = null;
		for (var i = 0; i < savedSearches.length; i++) {
			if (aras.getItemProperty(savedSearches[i], 'owned_by_id') == getWorldIdentityId()) {
				sharedSearches.push(savedSearches[i]);
			} else {
				if (aras.getItemProperty(savedSearches[i], 'auto_saved') != '1') {
					identityBasedSearches.push(savedSearches[i]);
				} else {
					autoSavedSearch = savedSearches[i];
				}
			}
		}

		if (sharedSearches.length > 0) {
			for (var i = 0; i < sharedSearches.length; i++) {
				AddSearchToComboBox(sharedSearches[i]);
			}

			if (identityBasedSearches.length > 0) {
				savedSearchChoice.addSeparator();
			}
		}

		for (var i = 0; i < identityBasedSearches.length; i++) {
			AddSearchToComboBox(identityBasedSearches[i]);
		}

		if (!autoSavedSearch) {
			autoSavedSearch = this._getAutoSavedSearch();
		}

		if (autoSavedSearch) {
			var autoSavedId = aras.getItemProperty(autoSavedSearch, 'id');
			AddSearchToComboBox(autoSavedSearch);
			savedSearchChoice.setSelected(autoSavedId);
			this.currentSavedSearchId = autoSavedId;
			notifyCuiLayout('SelectFavorite');
		}

		function AddSearchToComboBox(savedSearchNd) {
			var searchId = aras.getItemProperty(savedSearchNd, 'id');
			var searchLabel = aras.getItemProperty(savedSearchNd, 'label');
			if (searchLabel == undefined) {
				searchLabel = '';
			}

			savedSearchChoice.Add(searchId, searchLabel);
		}

		if (!this.toolbar.isButtonVisible('saved_search')) {
			this.toolbar.showItem('saved_search');
		} else {
			this.toolbar.refreshToolbar_Experimental();
		}
	};

	this._selectPrevSavedSearch = function() {
		if (!this.toolbar) {
			return;
		}

		var savedSearchChoice = this.toolbar.getItem('saved_search');
		if (savedSearchChoice) {
			savedSearchChoice.setSelected(this.currentSavedSearchId);
		}
	};

	this.applyFavoriteSearch = function(iomFavoriteItem) {
		this.currentFavoriteItem = iomFavoriteItem;
		const additionalData = iomFavoriteItem && iomFavoriteItem.getProperty('additional_data');
		const savedSearchId = additionalData ? JSON.parse(additionalData).id : null;
		this._onSavedSearchChange(savedSearchId);
	};

	this._onSavedSearchChange = function(savedSearchId) {
		var savedSearch = null;
		var savedSearches = aras.getSavedSearches(this.itemTypeName, this.searchLocation);
		if (savedSearches && savedSearches.length > 0) {
			for (var i = 0; i < savedSearches.length; i++) {
				if (aras.getItemProperty(savedSearches[i], 'id') == savedSearchId) {
					savedSearch = savedSearches[i];
					break;
				}
			}
		}

		if (!savedSearch && 'Search Dialog' == this.searchLocation) {
			var savedSearchesFromMainGrid = aras.getSavedSearches(itemTypeName, 'Main Grid');
			if (savedSearchesFromMainGrid && savedSearchesFromMainGrid.length > 0) {
				for (var i = 0; i < savedSearchesFromMainGrid.length; i++) {
					if (aras.getItemProperty(savedSearchesFromMainGrid[i], 'id') == savedSearchId) {
						savedSearch = savedSearchesFromMainGrid[i];
						break;
					}
				}
			}
		}

		if (!savedSearch) {
			notifyCuiLayout('SelectFavorite');
			return;
		}

		var sModeToShow = aras.getSearchMode(aras.getItemProperty(savedSearch, 'search_mode'));
		if (!sModeToShow) {
			return;
		}

		var sModeToShowId = aras.getItemProperty(sModeToShow, 'id');
		var criteriaToShow = aras.getItemProperty(savedSearch, 'criteria');
		if (aras.getItemProperty(savedSearch, 'auto_saved') == 1) {
			criteriaToShow = currentSearchMode.getAml();
		}

		if (!criteriaToShow) {
			criteriaToShow = '<Item type=\'' + this.itemTypeName + '\' action=\'get\'/>';
		}

		if (currentSearchMode.name == 'NoUI') {
			this.currentSavedSearchId = savedSearchId;
			this._updateAutoSavedSearch(criteriaToShow);
			this._setAml(criteriaToShow);
			notifyCuiLayout('SelectFavorite');
			return;
		}

		this.getCriteriaFromAutoSavedSearch = false;

		// If selected saved search has the same mode as the search mode currently set in UI then the selected search is rendered in UI.
		if (sModeToShowId == currentSearchMode.id) {
			var switchToNewMode = 'ok';
			var callback = function(swichMode) {
				switchToNewMode = swichMode || switchToNewMode;
				if ('ok' == switchToNewMode || 'clear' == switchToNewMode) {
					this.currentSavedSearchId = savedSearchId;
					if ('clear' == switchToNewMode) {
						currentSearchMode.clearSearchCriteria();
						criteriaToShow = currentSearchMode.getAml();
					}

					this._setAml(criteriaToShow);
					this._updateAutoSavedSearch(criteriaToShow);
				} else {
					this._selectPrevSavedSearch();
				}
				notifyCuiLayout('SelectFavorite');
			}.bind(this);
			var testResult = currentSearchMode.testAmlForCompatibility(criteriaToShow);
			if (currentSearchMode.name === 'Simple' && !testResult) {
				var switchToAml = aras.confirm(aras.getResource('', 'search_container.aml_is_not_compatible_with_simple_search_mode'));
				if (switchToAml) {
					this.getCriteriaFromAutoSavedSearch = true;
					this.currentSavedSearchId = savedSearchId;
					notifyCuiLayout('SelectFavorite');
					this._updateAutoSavedSearch(criteriaToShow);
					this.showSearchMode('BEF4CDA54AA74362A2C40BD530D4D9DD'); //Id of AML search mode
				} else {
					this.isSelectPrevSavedSearch = true;
					this._selectPrevSavedSearch();
					this.isSelectPrevSavedSearch = false;
				}
				return;
			}
			if (!testResult) {
				switchToNewMode = 'cancel';
				if (!currentSearchMode.isValidAML) {
					showIncompatibleAMLPromptDialog(currentSearchMode.label)
					.then(callback);
				} else {
					callback();
				}
			} else {
				callback();
			}
		} else {
			if (currentSearchMode.testAmlForCompatibility(criteriaToShow)) {
				this.currentSavedSearchId = savedSearchId;
				notifyCuiLayout('SelectFavorite');
				this._updateAutoSavedSearch(criteriaToShow);
				this._setAml(criteriaToShow);
			} else if (!this.isSelectPrevSavedSearch) {
				if (currentSearchMode.isValidAML) {
					this._selectPrevSavedSearch();
					return;
				}

				var currentSearchModeItem = aras.getSearchMode(currentSearchMode.id);
				var curModeLabel = aras.getItemProperty(currentSearchModeItem, 'label');
				var newModeLabel = aras.getItemProperty(sModeToShow, 'label');
				var bSwitchToNewSearchMode = aras.confirm(aras.getResource('', 'search_container.aml_is_not_compatible_with_new_search_mode2', curModeLabel, newModeLabel));
				if (bSwitchToNewSearchMode) {
					this.getCriteriaFromAutoSavedSearch = true;
					this.currentSavedSearchId = savedSearchId;
					notifyCuiLayout('SelectFavorite');
					this._updateAutoSavedSearch(criteriaToShow);
					if (this._ignoreAutoSavedSearch) {
						currentSearchMode.currQryItem.loadXML(criteriaToShow);
						this.getCriteriaFromAutoSavedSearch = false;
					}
					this.showSearchMode(sModeToShowId);
				} else {
					this.isSelectPrevSavedSearch = true;
					this._selectPrevSavedSearch();
					this.isSelectPrevSavedSearch = false;
				}
			}
		}
	};

	this._setAml = function(criteriaToShow) {
		criteriaToShow = this._applyDefaultSearchProperties(criteriaToShow);
		currentSearchMode.setAml(criteriaToShow);
		currentSearchMode.setSelect(aras.getSelectCriteria(getCurrentItemTypeId(), this.searchLocation == 'Relationships Grid', this.getVisibleXProps()));
	};

	function getCurrentItemTypeId() {
		return aras.getItemTypeId(itemTypeName);
	}

	this._transformAml = function(searchAML, indent) {
		/// <summary>
		/// Causes child elements to be indented.
		/// </summary>
		/// <param name="searchAML">AML to indent.</param>
		tmpXmlDocument.loadXML(searchAML);

		var stylesheet = aras.createXMLDocument();
		stylesheet.loadXML(
			'<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">' +
			'  <xsl:output method="xml" indent="' + (indent ? 'yes' : 'no') + '" omit-xml-declaration="yes"/>' +
			(indent ? '  ' : '  <xsl:strip-space elements="*" />') +
			'  <xsl:template match="*">' +
			'    <xsl:copy>' +
			'      <xsl:copy-of select="@*"/>' +
			'      <xsl:apply-templates/>' +
			'    </xsl:copy>' +
			'  </xsl:template>' +
			'  <xsl:template match="comment()|processing-instruction()">' +
			'    <xsl:copy/>' +
			'  </xsl:template>' +
			'</xsl:stylesheet>');

		return tmpXmlDocument.transformNode(stylesheet);
	};

	this._onSearchDialog = function SearchContainer_private_onSearchDialog(searchQueryAML) {
		var resItem = this._fireSearchEvents(searchQueryAML, true);
		searchQueryAML = resItem.item.xml;

		if (this._onSearchDialogEventMustBeInvoked()) {
			if (this.toolbar) {
				var searchModeChoice = this.toolbar.getItem('search_mode');
				var savedSearchChoice = this.toolbar.getItem('saved_search');
				if (!resItem.item.getAttribute('disableSearchMode')) {
					if (searchModeChoice) {
						searchModeChoice.disable();
					}
				}
				if (savedSearchChoice) {
					savedSearchChoice.disable();
				}
			}

			var searchModeToShow = '';
			if (resItem.item.getAttribute('idlist')) {
				searchModeToShow = 'NoUI';
				this.forceAutoSearch = true;
				if (this.toolbar) {
					var newSearchButton = this.toolbar.getItem('newsearch');
					if (newSearchButton) {
						//because user cannot clear search criteria when idlist is specified
						newSearchButton.disable();
					}
				}
			} else {
				searchModeToShow = this.defaultSearchMode;
			}

			if (resItem.item.getAttribute('searchMode')) {
				searchModeToShow = resItem.item.getAttribute('searchMode');
			}

			var sMode = this._getSearchModeByName(searchModeToShow);
			if (sMode) {
				var sModeId = aras.getItemProperty(sMode, 'id');
				if (sModeId != currentSearchMode.id) {
					this._updateAutoSavedSearch(searchQueryAML);
					this._onSearchModeChange(sModeId, true, resItem);
					return;
				}

				currentSearchMode.onSearchDialogUpdatesQueryExplicitly = onSearchDialogUpdatesQueryExplicitly;
				currentSearchMode.userMethodColumnCfgs = userMethodColumnCfgs;
			}
			if (searchQueryAML) {
				this._updateAutoSavedSearch(searchQueryAML);
				this._setAml(searchQueryAML);
			}
		}
	};

	this._onDefaultSearch = function SearchContainer_private_onDefaultSearch(searchQueryAML) {
		var resItem = this._fireSearchEvents(searchQueryAML, true);
		if (resItem.item) {
			searchQueryAML = resItem.item.xml;
		}

		if (searchQueryAML) {
			if (this._getSearchQueryAML() !== searchQueryAML) {
				this._updateAutoSavedSearch(searchQueryAML);
				this._setAml(searchQueryAML);
			}
		}
	};

	this._getSearchQueryAML = function SearchContainer_private_getSearchQueryAML(searchEventsResult) {
		var searchQueryAML;
		var re = new RegExp('^' + getCurrentItemTypeId() + '-');
		if (searchEventsResult) {
			searchQueryAML = searchEventsResult.item.xml;
		} else if (currentSearchMode && currentSearchFrame && currentSearchFrame.id.search(re) != -1 && !this.getCriteriaFromAutoSavedSearch) {
			searchQueryAML = currentSearchMode.getAml();
		} else {
			var autoSavedSearch = this._getAutoSavedSearch();
			searchQueryAML = aras.getItemProperty(autoSavedSearch, 'criteria');
		}
		return searchQueryAML;
	};

	this._onSearchModeChange = function SearchContainer_private_onSearchModeChange(searchModeId, isRecursiveCall, searchEventsResult) {
		if (this.redlineController && this.redlineController.IsRedlineCanBeDisable()) {
			this.redlineController.DisableRedline();
		}

		var newFrameId = getCurrentItemTypeId() + '-' + searchModeId;
		if (currentSearchFrame && currentSearchFrame.id == newFrameId) {
			return;
		}
		var newSearchIFrame = getSearchModeInstance(newFrameId, searchModeId, this);
		var newSearchMode = newSearchIFrame.searchMode;
		var searchQueryAML = this._getSearchQueryAML(searchEventsResult);
		var callback = function(swichMode) {
			var switchToNewMode = swichMode;
			if (switchToNewMode == 'ok' || switchToNewMode == 'clear') {
				// Continue – convert whatever is possible but drop conditions that could not be converted;
				// Clear – switch to Simple mode but clear all currently set conditions.

				// In AML search mode we need to indent AML, to make it readable for user.
				var amlSearchMode = this._getSearchModeByName('Aml');
				searchQueryAML = this._transformAml(searchQueryAML, (amlSearchMode && aras.getItemProperty(amlSearchMode, 'id') == searchModeId));

				// If switch to new search mode accepted, call onEndSearchMode method for currently loaded search mode.
				if (currentSearchMode && currentSearchMode.onEndSearchMode) {
					currentSearchMode.onEndSearchMode();
				}

				// Hide current search modes in search container.
				if (currentSearchMode && currentSearchMode.hide) {
					currentSearchMode.hide();
				} else if (currentSearchFrame && currentSearchFrame.style) {
					currentSearchFrame.style.display = 'none';
				}

				currentSearchMode = newSearchMode;
				currentSearchFrame = newSearchIFrame;
				// Show current search mode
				if (currentSearchMode.show) {
					currentSearchMode.show();
				} else if (currentSearchFrame.style) {
					currentSearchFrame.style.display = '';
				}

				// Call onStartSearchMode method for new search mode. Must be initialized by searchContainer object.
				if (currentSearchMode.onStartSearchMode) {
					currentSearchMode.onStartSearchMode(this);
				}

				if (switchToNewMode == 'clear') {
					currentSearchMode.clearSearchCriteria();
					searchQueryAML = currentSearchMode.getAml();
				}

				currentSearchMode.onSearchDialogUpdatesQueryExplicitly = onSearchDialogUpdatesQueryExplicitly;
				currentSearchMode.userMethodColumnCfgs = userMethodColumnCfgs;
				this._setAml(searchQueryAML);
				if (!onSearchDialogUpdatesQueryExplicitly) {
					this._updateAutoSavedSearch(searchQueryAML);
				}
			} else if (switchToNewMode == 'cancel' || !switchToNewMode) {
				// Cancel – do not switch mode;

				/*
				If rendering of the search is not possible in the lower complexity mode then a warning dialog appears:
				“The selected search could not be shown in {xxx} mode. Would you like to switch to {yyy} search mode?”
				If user says “Yes” then UI search mode is changed and selected search is rendered in UI;
				if user says “No” then UI remains unchanged (i.e. UI still shows old search criteria).
				*/
				if (!currentSearchFrame || !currentSearchMode) {
					var simpleSearchMode = this._getSearchModeByName(this.defaultSearchMode);
					if (simpleSearchMode) {
						this.showSearchMode(aras.getItemProperty(simpleSearchMode, 'id'));
					}

					return;
				}
			}

			const searchModeChoice = this.toolbar && this.toolbar.getItem('search_mode');
			if (searchModeChoice && searchModeChoice.getSelectedItem() !== currentSearchMode.id) {
				searchModeChoice.setSelected(currentSearchMode.id);
			}

			notifyCuiLayout('SearchStateChange');
		}.bind(this);

		// switchToNewMode can have next values:
		// Cancel – do not switch mode;
		// Continue - convert whatever is possible but drop conditions that could not be converted;
		// Clear - switch to Simple mode but clear all currently set conditions.
		if (searchQueryAML != undefined) {
			// Check AML compatibility with new search mode
			if (onSearchDialogUpdatesQueryExplicitly || newSearchMode.testAmlForCompatibility(searchQueryAML)) {
				callback('ok');
			} else {
				showIncompatibleAMLPromptDialog(newSearchMode.label)
				.then(callback).then(this._updateSearchMenu.bind(this));
			}
		} else {
			callback('cancel');
		}
	};

	this.attachEvents = [];
	this.toolbarEvents = [];

	this._attachEventHandlersToControls = function() {
		var tmpDojo, connectedEvent;
		if (this.grid) {
			tmpDojo = this._gridDojo;
			connectedEvent = tmpDojo.connect(this.grid, 'gridSort', gridSortEventHandler);
			this.attachEvents.push({ dojo: tmpDojo, func: connectedEvent });
		}
		if (this.toolbar) {
			if (this.toolbar._toolbar) {
				var self = this;
				this.toolbarEvents.push(this.toolbar._toolbar.on('change', function(itemId) {
					var item = self.toolbar.getItem(itemId);
					if (!item || !item.getEnabled()) {
						return;
					}
					toolbarOnChangeHandler(item);
				}));
				this.toolbarEvents.push(this.toolbar._toolbar.on('click', function(itemId) {
					var item = self.toolbar.getItem(itemId);
					if (!item || !item.getEnabled()) {
						return;
					}
					toolbarOnClickHandler(item);
				}));
			} else {
				tmpDojo = this._toolbarDojo;
				connectedEvent = tmpDojo.connect(this.toolbar, 'onClick', toolbarOnClickHandler);
				this.attachEvents.push({dojo: tmpDojo, func: connectedEvent});

				connectedEvent = tmpDojo.connect(this.toolbar, 'onChange', toolbarOnChangeHandler);
				this.attachEvents.push({dojo: tmpDojo, func: connectedEvent});
			}
		}
	};

	this._removeEventHandlersFromControls = function() {
		for (var i = 0; i < this.attachEvents.length; i++) {
			this.attachEvents[i].dojo.disconnect(this.attachEvents[i].func);
		}
		this.attachEvents = [];
		for (var i = 0; i < this.toolbarEvents.length; i++) {
			this.toolbarEvents[i]();
		}
		this.toolbarEvents = [];
	};

	this.removeIFramesCollection = function() {
		Object.keys(searchCollection).forEach(function(id) {
			const searchMode = searchCollection[id];
			if (searchMode.remove) {
				searchMode.remove();
			}
		})
	};

	this._updateAutoSavedSearch = function(searchQueryAML) {
		if (this._ignoreAutoSavedSearch || (!searchQueryAML && !currentSearchMode)) {
			return;
		}

		if (this.redlineController && this.redlineController.isRedlineActive) {
			return;
		}

		var autoSavedSearch = this._getAutoSavedSearch();
		if (!autoSavedSearch) {
			return;
		}

		var setEdit = false;

		if (currentSearchMode && currentSearchMode.id != aras.getItemProperty(autoSavedSearch, 'search_mode')) {
			// if we pass id as a param, setItemProperty method will send aml request to server."
			// It's because setItemProperty need KeyedName. That's why we need to get SearchMode Item from cache and pass it to setItemProperty
			var currentSearchModeItem = aras.getSearchMode(currentSearchMode.id);
			aras.setItemProperty(autoSavedSearch, 'search_mode', currentSearchModeItem);
			setEdit = true;
		}

		if (searchQueryAML == undefined) {
			searchQueryAML = currentSearchMode.getAml();
		}
		if (searchQueryAML != undefined) {
			if (this._onSearchDialogEventMustBeInvoked()) {
				if (onSearchDialogUpdatesQueryExplicitly) {
					var tmpQueryItm = aras.newQryItem(this.itemTypeName);
					tmpQueryItm.loadXML(searchQueryAML);
					tmpQueryItm.removeAllCriterias();
					tmpQueryItm.item.removeAttribute('idlist');
					tmpQueryItm.item.removeAttribute('disableSearchMode');
					tmpQueryItm.item.removeAttribute('searchMode');
					searchQueryAML = tmpQueryItm.item.xml;
				} else {
					tmpXmlDocument.loadXML(searchQueryAML);
					tmpXmlDocument.documentElement.removeAttribute('idlist');
					searchQueryAML = tmpXmlDocument.xml;
				}
			}

			if (aras.getItemProperty(autoSavedSearch, 'criteria') != searchQueryAML) {
				aras.setItemProperty(autoSavedSearch, 'criteria', searchQueryAML);
				setEdit = true;
			}
		}

		if (setEdit) {
			autoSavedSearch.setAttribute('action', 'edit');
		}
	};

	this._onSearchDialogEventMustBeInvoked = function() {
		if (this.searchLocation == 'Search Dialog' && sourceItemTypeName && sourcePropertyName) {
			var sourceItemTypeNd = aras.getItemTypeForClient(sourceItemTypeName, 'name');

			if (!sourceItemTypeNd || !sourceItemTypeNd.node) {
				return false;
			}

			return (sourceItemTypeNd.node.selectNodes
				('Relationships/Item[@type="Property" and name="' + sourcePropertyName + '"]/' +
				'Relationships/Item[@type="Grid Event" and grid_event="onsearchdialog"]/related_id/Item[@type="Method"]').length > 0);
		}
		return false;
	};

	this._updateSearchMenu = function() {
		if (!currentSearchMode) {
			return;
		}

		this._updateSaveDeleteMenu();
	};

	this._updateSaveDeleteMenu = function(selected_item) {
		var canDeleteSavedSearch = false;
		var canSaveSavedSearch = false;

		if (currentSearchMode.name != 'NoUI') {
			canSaveSavedSearch = true;

			if (this.toolbar && this.toolbar.isButtonVisible('saved_search')) {
				if (selected_item == undefined) {
					selected_item = this.toolbar.getItem('saved_search').getSelectedItem();
				}
				var autoSavedSearch = this._getAutoSavedSearch();
				if (aras.getItemProperty(autoSavedSearch, 'id') !== selected_item) {
					var savedSearch = getSavedSearch(selected_item);
					if (savedSearch) {
						canDeleteSavedSearch = aras.getPermissions('can_delete', selected_item, undefined, 'SavedSearch');
					}
				}
			}
		}
	};

	this._getSearchModeByName = function(sModeName) {
		if (!sModeName) {
			return null;
		}

		var modes = aras.getSearchModes();
		if (modes) {
			for (var i = 0; i < modes.length; i++) {
				if (aras.getItemProperty(modes[i], 'name') == sModeName) {
					return modes[i];
				}
			}
		}

		return null;
	};

	this._getAutoSavedSearch = function() {
		var autoSavedSearch = aras.getSavedSearches(this.itemTypeName, this.searchLocation, true);
		if (!autoSavedSearch || !autoSavedSearch.length) {
			//  If no auto_saved SavedSearch was found - create default new with
			//  auto_saved = 1
			//  owned_by_id = currently logged is_alias identity id.
			//  managed_by_id = currently logged is_alias identity id.
			//  search mode = this.defaultSearchMode
			var searchModeId;
			var sMode = this._getSearchModeByName(this.defaultSearchMode);
			if (sMode) {
				searchModeId = aras.getItemProperty(sMode, 'id');
			}
			autoSavedSearch = this._createNewSavedSearch(true, this._getDefaultSearchQueryAML(), searchModeId);
			autoSavedSearch = autoSavedSearch.apply();
			if (!autoSavedSearch.isEmpty() && !autoSavedSearch.isError()) {
				autoSavedSearch = autoSavedSearch.dom.selectSingleNode(aras.XPathResult('/Item'));
				autoSavedSearch = aras.getSavedSearches(this.itemTypeName, this.searchLocation, true, autoSavedSearch.getAttribute('id'));
			} else {
				aras.AlertError(autoSavedSearch, window);
				autoSavedSearch = null;
			}
		}
		if (autoSavedSearch) {
			autoSavedSearch = autoSavedSearch[0];
		}
		return autoSavedSearch;
	};

	this._createNewSavedSearch = function SearchContainer_private_createNewSavedSearch(isAutoSaved, criteria, searchModeId) {
		/// <summary>
		/// Creates but DOESN'T save an instance of SavedSearch.
		/// </summary>
		/// <param name="isAutoSaved" type="boolean">If specified, criteria will be populated with default_search property values.</param>
		/// <param name="criteria" type="boolean">AML query to store as criteria in the created SavedSearch instance.</param>
		/// <returns type="Item" mayBeNull="false">IOM Item</returns>

		//  If no auto_saved SavedSearch was found - create default new with
		//  auto_saved = 1
		//  owned_by_id = currently logged is_alias identity id.
		//  default search mode must be this.defaultSearchMode
		var aliasIdentityId = aras.getIsAliasIdentityIDForLoggedUser();

		var item = new Item('SavedSearch', 'add');
		item.setProperty('itname', this.itemTypeName);
		item.setProperty('auto_saved', (isAutoSaved ? '1' : '0'));
		item.setProperty('location', this.searchLocation);
		item.setProperty('owned_by_id', aliasIdentityId);
		item.setProperty('managed_by_id', aliasIdentityId);
		item.setProperty('criteria', criteria);
		if (searchModeId) {
			item.setProperty('search_mode', searchModeId);
		}
		return item;
	};

	this._getDefaultSearchQueryAML = function() {
		/// <summary>
		/// Generates default search aml for specified itemType.
		/// </summary>
		/// <returns type="string" mayBeNull="false">Returns string like <Item type="ItemTypeName" action="get" select="..."></Item></returns>
		var currItemType = this._getCurrentItemType();
		if (!currItemType) {
			return '';
		}

		var itTypeName = aras.getItemProperty(currItemType, 'name');
		var itTypeId = aras.getItemProperty(currItemType, 'id');
		var newCriteriaItem = aras.newQryItem(itTypeName, 'get');

		newCriteriaItem.setPage(1);
		newCriteriaItem.setSelect(aras.getSelectCriteria(itTypeId, this.searchLocation == 'Relationships Grid', this.getVisibleXProps()));

		var condition = aras.getPreferenceItemProperty('Core_GlobalLayout', null, 'core_use_wildcards') == 'true' ? 'like' : 'eq';
		var visiblePropsItms = currItemType.selectNodes(aras.getVisiblePropertiesXPath(itTypeName));
		for (i = 0; i < visiblePropsItms.length; i++) {
			var propName = aras.getItemProperty(visiblePropsItms[i], 'name');
			var defSearch = aras.getItemProperty(visiblePropsItms[i], 'default_search');
			var propDataType = aras.getItemProperty(visiblePropsItms[i], 'data_type');
			if (defSearch) {
				newCriteriaItem.setCriteria(propName, defSearch, ('boolean' == propDataType ? 'eq' : condition));
			}
		}

		return newCriteriaItem.item.xml;
	};

	this._getCurrentItemType = function() {
		var isSearchDialog = (this.searchLocation == 'Search Dialog');
		var currItemType;
		if (this.itemTypeCache[this.itemTypeName]) {
			currItemType = this.itemTypeCache[this.itemTypeName];
		} else {
			currItemType = aras.getItemTypeForClient(this.itemTypeName, 'name');
			this.itemTypeCache[this.itemTypeName] = currItemType;
		}
		if (currItemType.isError()) {
			if (isSearchDialog) {
				window.close();
			}
			return null;
		}

		return currItemType.node;
	};

	this._fireSearchEvents = function(searchAML, withDefaultSearch) {
		var newCriteriaItem = aras.newQryItem(this.itemTypeName);
		newCriteriaItem.loadXML(searchAML);

		if (this.searchLocation != 'Search Dialog') {
			//search events are applicable to Search Dialog only
			return newCriteriaItem;
		}

		var currItemType = this._getCurrentItemType();
		if (!currItemType) {
			return newCriteriaItem;
		}

		if (!this.requiredProperties) {
			this.requiredProperties = new Object();
		}

		if (!searchAML) {
			newCriteriaItem.loadXML(this._getSearchQueryAML());
		}

		var useWildcards = (aras.getPreferenceItemProperty('Core_GlobalLayout', null, 'core_use_wildcards') == 'true');

		var methodArgs = new Object();
		methodArgs.itemTypeName = itemTypeName;
		methodArgs.QryItem = newCriteriaItem;
		methodArgs.windowContext = searchArguments.aras;
		methodArgs.itemContext = searchArguments.itemContext;
		methodArgs.itemSelectedID = searchArguments.itemSelectedID;
		methodArgs.fromImplementationItemTypeName = fromImplementationItemTypeName; // input argument
		methodArgs.toImplementationItemTypeName = undefined; //output argument

		if (withDefaultSearch != false) {
			var propertiesWithDefaultSearchEvent = currItemType.selectNodes(
				'Relationships/Item[@type="Property"]/' +
				'Relationships/Item[@type="Grid Event" and grid_event="default_search"]/' +
				'related_id/Item[@type="Method"]'
			);

			for (var i = 0; i < propertiesWithDefaultSearchEvent.length; i++) {
				var methodNd = propertiesWithDefaultSearchEvent[i];
				var methodName = aras.getItemProperty(methodNd, 'name');

				var propNd = methodNd.selectSingleNode('../../../..');
				var propName = aras.getItemProperty(propNd, 'name');

				methodArgs.property_name = propName;
				var defSearch = aras.evalItemMethod(methodName, newCriteriaItem.item, methodArgs);
				if (defSearch) {
					if (-1 === this.grid.columns_Experimental.get(propName + '_D', 'index')) {
						this.defaultSearchProperties[propName] = defSearch;
					} else {
						var condition = ((useWildcards && /[%|*]/.test(defSearch)) ? 'like' : 'eq');
						var propDT = aras.getItemProperty(propNd, 'data_type');
						var propDS = aras.getItemPropertyAttribute(propNd, 'data_source', 'name');

						if ('item' == propDT) {
							newCriteriaItem.setPropertyCriteria(propName, 'keyed_name', defSearch, condition, propDS);
						} else {
							newCriteriaItem.setCriteria(propName, defSearch, condition);
						}
					}
				} else {
					newCriteriaItem.removeCriteria(propName);
				}
			}
		}

		if (sourceItemTypeName && sourcePropertyName) {
			var sourceItemTypeNd = aras.getItemTypeForClient(sourceItemTypeName, 'name');
			if (sourceItemTypeNd && sourceItemTypeNd.node) {
				var propertiesWithOnSearchEvent = sourceItemTypeNd.node.selectNodes(
					'Relationships/Item[@type="Property" and name="' + sourcePropertyName + '"]/' +
					'Relationships/Item[@type="Grid Event" and grid_event="onsearchdialog"]/' +
					'related_id/Item[@type="Method"]'
				);

				for (var index = 0; index < propertiesWithOnSearchEvent.length; index++) {
					var methodNd = propertiesWithOnSearchEvent[index];
					var methodName = aras.getItemProperty(methodNd, 'name');

					var propNd = methodNd.selectSingleNode('../../../..');
					var propName = aras.getItemProperty(propNd, 'name');

					var searchAmlBeforeMethod = '';
					if (newCriteriaItem.item != null) {
						searchAmlBeforeMethod = newCriteriaItem.item.xml;
					}
					userMethodColumnCfgs = aras.evalItemMethod(methodName, newCriteriaItem.item, methodArgs);

					if (methodArgs.QryItem.item != null && searchAmlBeforeMethod != methodArgs.QryItem.item.xml) {
						onSearchDialogUpdatesQueryExplicitly = true;
						if (currentSearchMode) {
							currentSearchMode.onSearchDialogUpdatesQueryExplicitly = true;
						}
						newCriteriaItem = methodArgs.QryItem;
					}

					if (!userMethodColumnCfgs || typeof (userMethodColumnCfgs) != 'object') {
						userMethodColumnCfgs = new Object();
					}

					var filteredPropName;
					for (filteredPropName in userMethodColumnCfgs) {
						if (!userMethodColumnCfgs[filteredPropName].filterValue) {
							userMethodColumnCfgs[filteredPropName].filterValue = '';
						}
						if (!userMethodColumnCfgs[filteredPropName].isFilterFixed) {
							userMethodColumnCfgs[filteredPropName].isFilterFixed = false;
						}
					}

					for (filteredPropName in userMethodColumnCfgs) {
						var filterValue = userMethodColumnCfgs[filteredPropName].filterValue;
						this.defaultSearchProperties[filteredPropName] = filterValue;

						if (filterValue) {
							var colNum = this.grid.GetColumnIndex(filteredPropName + '_D');
							if (colNum == -1 && userMethodColumnCfgs[filteredPropName].isFilterFixed) {
								this.requiredProperties[filteredPropName] = filterValue;
							} else {
								var condition = ((useWildcards && /[%|*]/.test(filterValue)) ? 'like' : 'eq');
								var propNd = currItemType.selectSingleNode('Relationships/Item[@type="Property" and name="' + filteredPropName + '"]');
								if (propNd && 'item' == aras.getItemProperty(propNd, 'data_type')) {
									var propDS = aras.getItemPropertyAttribute(propNd, 'data_source', 'name');
									newCriteriaItem.setPropertyCriteria(filteredPropName, 'keyed_name', filterValue, condition, propDS);
								} else {
									newCriteriaItem.setCriteria(filteredPropName, filterValue, condition);
								}
							}
						} else {
							newCriteriaItem.removeCriteria(filteredPropName);
						}
					}
				}
			}
		}

		if (methodArgs.toImplementationItemTypeName && methodArgs.toImplementationItemTypeName !== itemTypeName) {
			var implementationItemType = aras.getItemTypeForClient(itemTypeName, 'name').node;
			if (aras.isPolymorphic(implementationItemType)) {
				var switchToItemType = (itemTypeName == methodArgs.toImplementationItemTypeName) ? implementationItemType : implementationItemType.selectSingleNode('Relationships/Item[@type=\'Morphae\']/related_id/Item[name=\'' + methodArgs.toImplementationItemTypeName + '\']');
				if (switchToItemType) {
					var switchToItemTypeId = switchToItemType.getAttribute('id');
					setTimeout(function() {
						var searchToolbar = searchbar.getActiveToolbar();
						var cb = searchToolbar.getItem('implementation_type');
						cb.SetSelected(switchToItemTypeId);
					}, 1);
				} else {
					aras.AlertError('ItemType \'' + itemTypeName + '\' doesn\'t contain morhae \'' + methodArgs.toImplementationItemTypeName + '\'');
				}
			}
		}
		fromImplementationItemTypeName = itemTypeName;

		return newCriteriaItem;
	};

	this._isSearchCriteriaEmpty = function(searchAML) {
		if (!searchAML) {
			return true;
		}

		var newCriteriaItem = aras.newQryItem(this.itemTypeName);
		newCriteriaItem.loadXML(searchAML);
		return (newCriteriaItem.dom.documentElement.childNodes.length == 0);
	};

	this._initSearchMode = function() {
		/// <summary>
		///   Gets searchMode from auto_saved SavedSearch and loads it into the UI.
		/// </summary>
		/// <remarks>
		///   If no auto_saved SavedSearch found, "Simple" search mode will be shown.
		/// </remarks>
		let searchModeId = '';
		const autoSavedSearch = this._getAutoSavedSearch();

		if (autoSavedSearch && !this._onSearchDialogEventMustBeInvoked()) {
			this.searchCriteria = aras.getItemProperty(autoSavedSearch, 'criteria');
			if (!this._isSearchCriteriaEmpty(this.searchCriteria)) {
				searchModeId = aras.getItemProperty(autoSavedSearch, 'search_mode');
				const sMode = aras.getSearchMode(searchModeId);
				if (!sMode) {
					searchModeId = '';
				}
			}
		}

		if (!searchModeId) {
			// If no SearchMode with specified id found, try to use this.defaultSearchMode search.
			const simpleSearchMode = this._getSearchModeByName(this.defaultSearchMode);
			if (simpleSearchMode) {
				searchModeId = aras.getItemProperty(simpleSearchMode, 'id');
			} else {
				// If this.defaultSearchMode search not found - use any available SearchMode.
				const modes = aras.getSearchModes();
				if (modes && modes.length > 0) {
					searchModeId = aras.getItemProperty(modes[0], 'id');
				}
			}
		}

		this.showSearchMode(searchModeId);
	};
	// ************************************* End of privileged SearchContainer members *************************************
}

SearchContainer.prototype.initSearchContainer = function SearchContainer_initSearchContainer(ignoreAutoSavedSearch) {
	/// <summary>
	/// Initialize search container.
	/// </summary>
	/// <param name="ignoreAutoSavedSearch">Flag for ignoring autoSavedSearch criterias and searchMode.</param>
	this._ignoreAutoSavedSearch = ignoreAutoSavedSearch;
	this._initSearchModesInToolbar();
	this._initSavedSearchesInToolbar();
	this._initSearchMode();
	if (this._onSearchDialogEventMustBeInvoked()) {
		this._onSearchDialog();
	} else {
		this._onDefaultSearch(this.searchCriteria);
	}
};

SearchContainer.prototype.defaultSearchMode = 'Simple';
SearchContainer.prototype.forceAutoSearch = false;

SearchContainer.prototype.getGrid = function SearchContainer_getGrid() {
	/// <summary>
	/// Gets grid object used to display search results.
	/// </summary>
	/// <returns type="Aras.Client.Controls.GridContainer" mayBeNull="true">TreeTable instance used by search.</returns>
	return this.grid;
};

SearchContainer.prototype.getToolbar = function SearchContainer_getToolbar() {
	/// <summary>
	/// Gets toolbar object containing search elements.
	/// </summary>
	/// <returns type="Aras.Client.Controls.Toolbar" mayBeNull="true">Toolbar instance used by search.</returns>
	return this.toolbar;
};

SearchContainer.prototype.getMenu = function SearchContainer_getMenu() {
	/// <summary>
	/// Gets menu object containing search control objects.
	/// </summary>
	/// <returns type="Aras.Client.Controls.MainMenu" mayBeNull="true">MainMenu instance used by search.</returns>
	return ;
};

SearchContainer.prototype.getStyleAttribute = function SearchContainer_getStyleAttribute(strAttributeName) {
	/// <summary>
	/// Retrieves the value of the specified Style attribute of the SearchContainer.
	/// </summary>
	/// <param name="strAttributeName">Name of the attribute.</param>
	/// <returns>
	/// Variant that returns a String, number, or Boolean value as defined by the attribute.
	/// If the attribute is not present, this method returns null.
	/// </returns>
	this.searchPlaceholder.style.getAttribute(strAttributeName, attributeValue);
};

SearchContainer.prototype.setStyleAttribute = function SearchContainer_setStyleAttribute(strAttributeName, attributeValue) {
	/// <summary>
	/// Sets the value of the specified CSS attribute on the DOM element associated with <see cref="SearchContainer"/>.
	/// </summary>
	/// <remarks>
	///   Can be used to set height, visibility, etc. attributes.
	/// </remarks>
	/// <param name="strAttributeName">Name of the attribute.</param>
	/// <param name="attributeValue">Variant that specifies the string, number, or Boolean to assign to the attribute.</param>
	if (strAttributeName != 'height') {
		this.searchPlaceholder.style[strAttributeName] = attributeValue;
	}

	if (this.searchPlaceholderCell) {
		this.searchPlaceholderCell.style[strAttributeName] = attributeValue;
	}

	if (strAttributeName == 'height' && typeof(this.grid.RefreshHeight) == 'function') {
		this.grid.RefreshHeight();
	}
};

SearchContainer.prototype.getRequiredProperties = function SearchContainer_getRequiredProperties() {
	/// <summary>
	/// Gets requiredProperties object for SearchContainer.
	/// </summary>
	/// <returns type="Object">Object representing key/value collection of XPath to properties and values.</returns>
	return this.requiredProperties;
};

SearchContainer.prototype.setRequiredProperties = function SearchContainer_setRequiredProperties(requiredPropertiesObject) {
	/// <summary>
	/// Sets requiredProperties object for SearchContainer.
	/// </summary>
	/// <remarks>
	/// In some cases SearchMode must return query containing immutable properties/values.
	/// This method allows user to specify such immutable criterias.
	/// </remarks>
	/// <example>
	/// <code language="JavaScript">
	/// <![CDATA[
	///   var reqProperties = new Object();
	///   reqProperties["source_id/Item[@type='MySourceItem']/name"] = 'my_item_name';
	///   reqProperties["related_id/Item[@type='MyRelatedItem']/label"] = 'related_item_label';
	///   searchContainer.setRequiredProperties(reqProperties);
	///   // In this case SearchMode.getAml() method will always return query containing next aml:
	///   // ....
	///   // <source_id>
	///   //  <Item type='MySourceItem'>
	///   //    <name>my_item_name</name>
	///   //  </Item>
	///   // </source_id>
	///   // <related_id>
	///   //  <Item type='MyRelatedItem'>
	///   //    <label>related_item_label</label>
	///   //  </Item>
	///   // </related_id>
	///   // ....
	/// ]]>
	/// </code>
	/// </example>
	/// <param name="requiredPropertiesObject">Object representing key/value collection of XPath to properties and values.</param>
	this.requiredProperties = requiredPropertiesObject;
};

SearchContainer.prototype.getPropertyDefinitionByColumnIndex = function SearchContainer_getPropertyDefinitionByColumnIndex(columnIdx) {
	/// <summary>
	/// Gets definition for property corresponding to column in the grid with specified index.
	/// </summary>
	/// <remarks>
	/// Some SearchModes could use information from grid as source data for search query generation.
	/// And in some cases it will be required to know what property corresponds to the column.
	/// </remarks>
	/// <param name="columnIdx" type="Number" integer="true">Index of the column in grid.</param>
	/// <returns type="System.Xml.XmlNode">XmlNode containing property info.</returns>
	var propNd = null;

	if (!this.grid || columnIdx === undefined) {
		return null;
	}

	var columnName = this.grid.GetColumnName(columnIdx);
	var drl = columnName.substr(columnName.length - 2, columnName.length);
	var propertyName = columnName.substr(0, columnName.length - 2);
	if (columnName == 'L') {
		propertyName = 'locked_by_id';
		if (searchLocation == 'Relationships Grid') {
			drl = '_R';
		} else {
			drl = '_D';
		}
	}

	const handleXPropertyDefinition = function(propertyName, propertyXPath, itemTypeNd) {
		const propNd = itemTypeNd.selectSingleNode(propertyXPath);
		aras.setItemProperty(propNd, 'source_id', itemTypeNd.getAttribute('id'));
		aras.setItemPropertyAttribute(propNd, 'source_id', 'name', aras.getItemProperty(itemTypeNd, 'name'));
		return propNd;
	};

	var propXPath;
	var currItemType = this._getCurrentItemType();
	const isXProperty = propertyName.startsWith('xp-');
	if (isXProperty) {
		propXPath = 'Relationships/Item[@type=\'xItemTypeAllowedProperty\']/related_id/Item[@type=\'xPropertyDefinition\' and name=\'' + propertyName + '\']';
	} else {
		propXPath = 'Relationships/Item[@type=\'Property\' and name=\'' + propertyName + '\']';
	}

	if (drl == '_D') {
		if (currItemType) {
			if (isXProperty) {
				propNd = handleXPropertyDefinition(propertyName, propXPath, currItemType);
			} else {
				propNd = currItemType.selectSingleNode(propXPath);
			}
		}
	} else if (drl == '_R') {
		var relshipTypeNd = aras.getRelationshipType(aras.getRelationshipTypeId(this.itemTypeName));
		if (relshipTypeNd && relshipTypeNd.node) {
			var relatedId = aras.getItemProperty(relshipTypeNd.node, 'related_id');
			if (relatedId) {
				var relatedItemTypeNd = aras.getItemTypeDictionary(relatedId, 'id');
				if (relatedItemTypeNd && relatedItemTypeNd.node) {
					if (isXProperty) {
						propNd = handleXPropertyDefinition(propertyName, propXPath, relatedItemTypeNd.node);
					} else {
						propNd = relatedItemTypeNd.node.selectSingleNode(propXPath);
					}
				}
			}
		}
	}

	return propNd;
};

SearchContainer.prototype.getPropertyXPathByColumnIndex = function SearchContainer_getPropertyXPathByColumnIndex(columnIdx) {
	/// <summary>
	/// Gets XPath to property corresponding to the column in the grid with specified index.
	/// </summary>
	/// <remarks>
	/// Some SearchModes could use information from grid as source data for search query generation.
	/// For example "Simple" search mode works in such way.
	/// This method allows to get explicitly path to criteria in search criteria dom.
	/// </remarks>
	/// <param name="columnIdx" type="Number" integer="true">Index of the column in grid.</param>
	/// <returns type="string">XPath to the property in grid; returns undefined in case when there are no grid or columnIdx not specified.</returns>
	var XPath = undefined;

	if (!this.grid || columnIdx === undefined) {
		return undefined;
	}

	var propNd = this.getPropertyDefinitionByColumnIndex(columnIdx);
	if (propNd) {
		XPath = 'Item[@type=\'' + this.itemTypeName + '\']/';
		var columnName = this.grid.GetColumnName(columnIdx);
		var drl = columnName.substr(columnName.length - 2, columnName.length);
		var sourceTypeName = propNd.selectSingleNode('source_id').getAttribute('name');

		if (drl == '_R' || (drl == 'L' && searchLocation == 'Relationships Grid')) {
			XPath += 'related_id/Item[@type=\'' + sourceTypeName + '\']/';
		}

		XPath += aras.getItemProperty(propNd, 'name');
	}

	return XPath;
};

SearchContainer.prototype.showSearchMode = function SearchContainer_showSearchMode(searchModeId) {
	/// <summary>
	/// Shows SearchMode in SearchContainer.
	/// </summary>
	/// <remarks>
	/// Method loads SearchMode into SearchContainer and initialize it with current search criteria.
	/// </remarks>
	/// <param name="searchModeId">Id of search mode to show.</param>
	this._onSearchModeChange(searchModeId);
	this._updateSearchMenu();
};

SearchContainer.prototype.onEndSearchContainer = function SearchContainer_onEndSearchContainer() {
	/// <summary>
	/// This method have sense in case when you work with more than one SearchContainer.
	/// Method resets Search menu and removes handlers from controls for currently selected SearchContainer instance.
	/// </summary>
	this._updateAutoSavedSearch();
	this._removeEventHandlersFromControls();
};

SearchContainer.prototype.onStartSearchContainer = function SearchContainer_onStartSearchContainer() {
	/// <summary>
	/// This method have sense in case when you work with more than one SearchContainer. If you switch between them you may need to reinitilize controls.
	/// Method reinitializes Search menu and forces controls to work with currently selected SearchContainer instance.
	/// </summary>
	/// <remarks>
	/// You don't need to call this method if constructor of the SearchContainer is called.
	/// </remarks>
	this._updateSearchMenu();
	this._attachEventHandlersToControls();
};

SearchContainer.prototype.runSearch = function SearchContainer_runSearch() {
	/// <summary>
	/// This method have sense in case when you work with more than one SearchContainer. If you switch between them you may need to reinitilize controls.
	/// Method reinitializes Search menu and forces controls to work with currently selected SearchContainer instance.
	/// </summary>
	/// <remarks>
	/// You don't need to call this method if constructor of the SearchContainer is called.
	/// </remarks>
	var searchAml = currentSearchMode.getAml();
	if (searchAml != undefined) {
		this._updateAutoSavedSearch(searchAml);
		searchAml = this._transformAml(searchAml, false);

		this.searchParameterizedHelper.replaceParametersInQuery(searchAml, null, function(searchAml) {
			if (searchAml != undefined) {
				searchAml = this._applyDefaultSearchProperties(searchAml);
				searchAml = this._applyRequiredProperties(searchAml);
				currQryItem.loadXML(searchAml);
				doSearch_internal();
			}
		}.bind(this));
	}
};

SearchContainer.prototype.runAutoSearch = function SearchContainer_runAutoSearch() {
	/// <summary>
	/// Determines if search should be started automatically. And if should starts the search.
	/// </summary>
	var startSearch = this.forceAutoSearch;

	if (!startSearch) {
		var currItemType = this._getCurrentItemType();
		if (currItemType) {
			startSearch = (aras.getItemProperty(currItemType, 'auto_search') == '1');
		}
	}

	if (startSearch) {
		this.runSearch();
	}
};

SearchContainer.prototype._isNoCountModeForCurrentItemType = function() {
	var countModeExc = aras.getCommonPropertyValue('SearchCountModeException');
	var countModeShowCount = (aras.getCommonPropertyValue('SearchCountMode').toLowerCase() === 'count');
	var itemId = this._getCurrentItemType().attributes.getNamedItem('id').value;
	return countModeShowCount === (countModeExc.indexOf(itemId) > -1);
};

SearchContainer.prototype.getVisibleXProps = function(currItemTypeId) {
	var self = this;
	var colWidths = this.grid.getColWidths().split(';');

	let currItemType;
	if (currItemTypeId) {
		currItemType = aras.getItemTypeForClient(currItemTypeId, 'id');
		if (currItemType && !currItemType.isError()) {
			currItemType = currItemType.node;
		} else {
			return;
		}
	} else {
		currItemType = this._getCurrentItemType();
		currItemTypeId = aras.getItemProperty(currItemType, 'id');
	}

	const currItemTypeName = aras.getItemProperty(currItemType, 'name');
	const isRelationshipType = (aras.getItemProperty(currItemType, 'is_relationship') == '1');

	var currItemTypeXProperties = this.grid.getLogicalColumnOrder().split(';').reduce(function(prev, curr, idx) {
		var propName = self.grid.GetColumnName(idx).slice(0, -2);
		if (propName.startsWith('xp-') && colWidths[idx] !== '0') {
			const propXPath = 'Relationships/Item[@type=\'xItemTypeAllowedProperty\' and not(inactive=\'1\')]/related_id/Item[@type=\'xPropertyDefinition\' and name=\'' + propName + '\']';
			const xProp = currItemType.selectSingleNode(propXPath);
			if (xProp) prev.add(xProp);
		}
		return prev;
	}, new Set());

	const allXProperties = {};
	allXProperties[currItemTypeId] = [];
	currItemTypeXProperties.forEach(function(el) {
		allXProperties[currItemTypeId].push(el);
	});
	if (isRelationshipType) {
		const relType = aras.getRelationshipType(aras.getRelationshipTypeId(currItemTypeName));
		if (relType && !relType.isError()) {
			const relatedTypeId = relType.getProperty('related_id');
			if (relatedTypeId) {
				allXProperties.related = this.getVisibleXProps(relatedTypeId);
			}
		}
	}
	return allXProperties;
};

SearchContainer.prototype.isFavoriteSearchChanged = function() {
	if (!this.currentFavoriteItem) {
		return false;
	}

	const additionalData = this.currentFavoriteItem.getProperty('additional_data');
	const currentSavedSearchId = JSON.parse(additionalData).id;
	const autoSavedOnly = false;
	const savedSearches = aras.getSavedSearches(
		this.itemTypeName,
		this.searchLocation,
		autoSavedOnly,
		currentSavedSearchId
	);
	const currentSavedSearch = savedSearches[0];
	if (!currentSavedSearch) {
		return false;
	}

	const getCriterias = function(xml) {
		const transformedXml = this._transformAml(xml, false);
		const qryItem = aras.newQryItem(this.itemTypeName);
		qryItem.loadXML(transformedXml);

		return qryItem.getCriteriesString();
	}.bind(this);

	const savedSearchAml = aras.getItemProperty(currentSavedSearch, 'criteria');
	const currentAppliedAml = currentSearchMode.getAml();

	return getCriterias(savedSearchAml) !== getCriterias(currentAppliedAml);
};
/*@cc_on
@if (@register_classes == 1)
Type.registerNamespace("Aras");
Type.registerNamespace("Aras.Client");
Type.registerNamespace("Aras.Client.JS");

Aras.Client.JS.SearchContainer = SearchContainer;
Aras.Client.JS.SearchContainer.registerClass("Aras.Client.JS.SearchContainer");
@end
@*/

/** SearchParameterizedHelper.js **/
function SearchParameterizedHelper(tmpXmlDocument) {
	this.tmpXmlDocument = tmpXmlDocument ? tmpXmlDocument : aras.createXMLDocument();
}

SearchParameterizedHelper.prototype.replaceParametersInQuery = function(searchAml, isForProjectTree, callback) {
	const searchFormParams = this.prepareSearchFormParametersInQuery(searchAml, isForProjectTree);
	if (searchFormParams) {
		this.showSearchForm(searchAml, isForProjectTree, callback, searchFormParams);
	} else {
		callback(searchAml);
	}
};

SearchParameterizedHelper.prototype.prepareSearchFormParametersInQuery = function(searchAml, isForProjectTree) {
	const tmpXmlDocument = this.tmpXmlDocument;
	let fakeForm;
	let fakeItemType;
	function appendParamIntoParamsArray(nodeName, nodeValue, labelTextToAdd, addAsText) {
		const matches = isForProjectTree ? nodeValue.replace(/,text="[^"]*"/, '').match(/@{(\d+)}/g) : nodeValue.match(/@{(\d+)}/g);
		let i;

		if (matches) {
			for (i = 0; i < matches.length; i++) {
				const paramNumber = /@{(\d+)}/g.exec(matches[i])[1];

				// If parameter occured more that once - set field type to text.
				if (addAsText || parametersArray[paramNumber]) {
					parametersArray[paramNumber] = {
						param_number: paramNumber,
						propertyItem: undefined
					};
				} else {
					let propertyItem;
					let oldPropertyItemId;
					const xPath = '//' + nodeName + '[.=\'' + nodeValue + '\']';
					let nd = tmpXmlDocument.selectSingleNode(xPath);

					while (nd) {
						if (nd.nodeName == 'Item') {
							const type = nd.getAttribute('type');
							const typeId = nd.getAttribute('typeId');
							if (type || typeId) {
								const itemTypeForClient = aras.getItemTypeForClient((type ? type : typeId), (type ? 'name' : 'id'));
								if (itemTypeForClient && itemTypeForClient.node) {
									propertyItem = itemTypeForClient.getItemsByXPath('Relationships/Item[@type=\'Property\' and name=\'' + nodeName + '\']');
									oldPropertyItemId = propertyItem.getID();
									propertyItem = propertyItem.clone(true);
									propertyItem.setNewID();
								}

								break;
							} else if (!nd.parentNode) {
								break;
							} else {
								if (nodeName == 'keyed_name') {
									const parentNodeName = nd.parentNode.nodeName;
									if (parentNodeName != 'related_id' && parentNodeName != 'source_id') {
										nodeName = parentNodeName;
										nd = nd.parentNode;
									} else {
										break;
									}
								} else {
									break;
								}
							}
						} else {
							nd = nd.parentNode;
						}
					}

					parametersArray[paramNumber] = {
						param_number: paramNumber,
						propertyItem: propertyItem,
						oldPropertyItemId: oldPropertyItemId,
						labelTextToAdd: labelTextToAdd
					};
				}
			}
		}
	}

	function generateFormToPopulateParams() {
		const bodyNd = fakeForm.selectSingleNode('Relationships/Item[@type="Body"]');
		let i;
		let propertyItem;
		let fieldType;
		let inputProperty;

		for (i = 0; i < parametersArray.length; i++) {
			const cur_param = parametersArray[i];
			if (!cur_param) {
				continue;
			}

			if (!cur_param.propertyItem) {
				cur_param.propertyItem = aras.newIOMItem('Property');
				cur_param.propertyItem.setNewID();
				cur_param.propertyItem.setProperty('data_type', 'string');
			}

			propertyItem = cur_param.propertyItem;
			fieldType = aras.uiGetFieldType4Property(propertyItem.node);
			const propertyDataType = propertyItem.getProperty('data_type');
			if ('sequence' === propertyDataType) {
				propertyItem.setProperty('data_type', 'string');
				propertyItem.removeProperty('data_source');
				propertyItem.setProperty('data_source', '');
				propertyItem.setPropertyAttribute('data_source', 'is_null', '1');
			}
			propertyItem.setProperty('name', 'parameter' + i);
			propertyItem.setProperty('readonly', '0');
			fakeItemType.addRelationship(propertyItem);
			inputProperty = insertNewField(fieldType, cur_param.param_number, propertyItem, cur_param.oldPropertyItemId, cur_param.labelTextToAdd);
		}

		const btnOk = insertNewField('button', i, null);
		btnOk.setProperty('label', aras.getResource('', 'common.ok'));
		i++;
		const btnCancel = insertNewField('button', i, null);
		btnCancel.setProperty('label', aras.getResource('', 'common.cancel'));
		btnCancel.setProperty('x', parseInt(btnOk.getProperty('x'), 10) + 100);
		btnCancel.setProperty('y', btnOk.getProperty('y'));
		const htmlField = insertNewField('html', 'html1', null);
		htmlField.setProperty('is_visible', 0);
		htmlField.setProperty('html_code',
			'<script type="text/javascript">' +
			'var okButton,cancelButton;  \n' +
			'function onload_handler()\n' +
			'{\n' +
			'	var parametersArray = (parent.dialogArguments || parent.parent.dialogArguments).parametersArray;\n' +
			'	if (!parametersArray || parametersArray.length == 0)\n' +
			'		closeWindow(null);\n' +
			'	okButton = document.getElementById("' + btnOk.GetId() + '");\n' +
			'	okButton.addEventListener("click", getResult, false);\n' +
			'	cancelButton = document.getElementById("' + btnCancel.GetId() + '");\n' +
			'	cancelButton.addEventListener("click", onCancelClicked, false);\n' +
			'	document.body.addEventListener("keypress", onKeyPressHandler, false); // 4 ie \n' +
			'	parent.addEventListener("keypress", onKeyPressHandler, false); // 4 ff \n' +
			'	function getResult() {\n' +
			'		if (isAllParametersFilled(document.item)) {\n' +
			'			closeWindow(document.item);\n' +
			'		}\n' +
			'	}\n' +
			'	function onKeyPressHandler(e)\n' +
			'	{\n' +
			'		var evnt = e || event;\n' +
			'		if (evnt.keyCode == 27)\n' +
			'			closeWindow(null);\n' +
			'	}\n' +
			'	function isAllParametersFilled(resultItem) {\n' +
			'		var i,\n' +
			'			paramValue;\n' +
			'		for (i = 0; i < parametersArray.length; i++) {\n' +
			'			if (!parametersArray[i]) {\n' +
			'				continue;\n' +
			'			}\n' +
			'			paramValue = parent.aras.getItemProperty(resultItem, parametersArray[i].propertyItem.getProperty("name"))\n' +
			'			if (paramValue === undefined ||paramValue === null || paramValue === "") {\n' +
			'				parent.aras.AlertWarning(parent.aras.getResource("", "search.not_all_parameters_filled"), parent.aras.getMostTopWindowWithAras(parent))\n' +
			'				return false;\n' +
			'			}\n' +
			'		}\n' +
			'		return true;' +
			'	}\n' +
			'	function onCancelClicked() {\n' +
			'		closeWindow(null);\n' +
			'	}\n' +
			'	function closeWindow(returnValue)\n' +
			'	{\n' +
			'		parent.returnValue = returnValue;\n' +
			'		parent.close();\n' +
			'	}\n' +
			'}\n' +
			'window.addEventListener("load", onload_handler, false);\n' +
			'</script>');

		function insertNewField(fieldType, paramNumber, propertyItem, oldPropertyItemId, labelTextToAdd) {
			const fieldNds = bodyNd.selectNodes('Relationships/Item[@type="Field" and (not(@action) or (@action!="delete" and @action!="purge"))]');
			let yForNewField = 10;
			let i;
			let fieldY;
			let labelNd;
			const propertyItemId = propertyItem ? propertyItem.getID() : '';

			for (i = 0; i < fieldNds.length; i++) {
				fieldY = parseInt(aras.getItemProperty(fieldNds[i], 'y'), 10);
				if (!isNaN(fieldY)) {
					yForNewField = fieldY + 60;
				}
			}

			const newFieldNd = aras.newIOMItem('Field');
			newFieldNd.setProperty('name', paramNumber);
			newFieldNd.setProperty('field_type', fieldType);
			newFieldNd.setAttribute('id', aras.generateNewGUID());

			let newLabel = aras.getResource('', 'search.parameter_label') + ' ' + paramNumber;
			const sessionLanguageCode = aras.getSessionContextLanguageCode();

			if (oldPropertyItemId) {
				const tmpItem = aras.getItemById('Property', oldPropertyItemId, 0, undefined, 'label');
				if (tmpItem) {
					const propLabelNds = tmpItem.selectNodes('*[local-name()=\'label\']');
					for (i = 0, length = propLabelNds.length; i < length; i++) {
						labelNd = newFieldNd.node.appendChild(propLabelNds[i].cloneNode(true));
						if (labelNd.text.length === 0) {
							labelNd.text = paramNumber;
						}
					}
					labelNd = newFieldNd.node.selectSingleNode('*[local-name()=\'label\' and @xml:lang=\'' + sessionLanguageCode + '\']');
					if (labelNd) {
						newLabel = labelNd.text;
						newFieldNd.node.removeChild(labelNd);
					}
				}
			}

			newFieldNd.setProperty('label', newLabel + (labelTextToAdd || ''));
			newFieldNd.setPropertyAttribute('label', 'xml:lang', sessionLanguageCode);

			newFieldNd.setProperty('label_position', 'top');
			newFieldNd.setProperty('x', '20');
			newFieldNd.setProperty('y', yForNewField);
			newFieldNd.setProperty('is_visible', 1);
			newFieldNd.setProperty('border_width', '0');
			newFieldNd.setProperty('font_family', 'arial, helvetica, sans-serif');
			newFieldNd.setProperty('font_size', '8pt');
			newFieldNd.setProperty('font_weight', 'bold');
			newFieldNd.setProperty('font_align', 'right');
			newFieldNd.setProperty('font_color', '#000000');
			newFieldNd.setProperty('tab_stop', '1');
			newFieldNd.setProperty('tab_index', parseInt(paramNumber, 10) + 1);
			newFieldNd.setProperty('propertytype_id', propertyItemId);

			let bodyRelshipsNd = bodyNd.selectSingleNode('Relationships');
			if (!bodyRelshipsNd) {
				bodyRelshipsNd = bodyNd.appendChild(bodyNd.ownerDocument.createElement('Relationships'));
			}

			bodyRelshipsNd.appendChild(newFieldNd.node);

			return newFieldNd;
		}
	}

	// Search for any @{n} parameter in Aml.
	if (!/@{(\d+)}/g.test(searchAml)) {
		//only if isForProjectTree is truthy then test if we have {d+,text=""} not to degrade perfomance all over the Innovator Searches.
		if (!isForProjectTree || !/@{(\d+,text="[^"]*")}/g.test(searchAml)) {
			return;
		}
	}

	// If parameter represents the whole criteria value for a property.
	//<Item type="Action" action="get">
	//  <name condition="like">@{1}</name>
	//</Item>
	const parametersArray = [];

	this.tmpXmlDocument.loadXML(searchAml);

	let regExp = />(@{\d+})<\/(\w*)>/g;
	let wholeCriteria = regExp.exec(searchAml);

	while (wholeCriteria != null) {
		appendParamIntoParamsArray(wholeCriteria[2], wholeCriteria[1], '', false);

		wholeCriteria.lastIndex = 0;
		wholeCriteria = regExp.exec(searchAml);
	}

	if (isForProjectTree) {
		regExp = />(@{\d+,text="([^"]*)"})<\/(\w*)>/g;
		wholeCriteria = regExp.exec(searchAml);
		while (wholeCriteria != null) {
			appendParamIntoParamsArray(wholeCriteria[3], wholeCriteria[1], wholeCriteria[2], false);

			wholeCriteria.lastIndex = 0;
			wholeCriteria = regExp.exec(searchAml);
		}
	}

	// If parameter represents a portion of the criteria value for a property.
	//<Item type="Action" action="get">
	//  <OR>
	//    <size>@{0}</size>
	//    <weight condition="eq">my weight is @{4}</weight>
	//    <age condition="like">@{3} is my age</age>
	//    <name condition="like">first name is @{1} and second is @{2}</name>
	//  </OR>
	//</Item>
	regExp = new RegExp('<(\\w+)[^>]*>([^>]+@{\\d+}[^>]*|[^>]*@{\\d+}[^>]+)</\\w+>', 'g');
	let portionOfTheCriteria = regExp.exec(searchAml);
	while (portionOfTheCriteria != null) {
		appendParamIntoParamsArray(portionOfTheCriteria[1], portionOfTheCriteria[2], '', true);

		portionOfTheCriteria.lastIndex = 0;
		portionOfTheCriteria = regExp.exec(searchAml);
	}

	// If parameter is encountered in the where attribute of the search AML.
	const whereAttr = this.tmpXmlDocument.documentElement.getAttribute('where');
	if (whereAttr) {
		appendParamIntoParamsArray('', whereAttr, '', true);
	}

	let param;
	if (parametersArray.length > 0) {

		fakeForm = aras.newItem('Form');
		fakeItemType = aras.newIOMItem('ItemType');

		fakeItemType.setNewID();
		const fakeItemTypeName = 'fake_SearchContainer_' + fakeItemType.getID();
		fakeItemType.setProperty('name', fakeItemTypeName);
		const fakeItem = aras.newIOMItem(fakeItemTypeName, 'add');
		fakeItem.setNewID();
		generateFormToPopulateParams();

		if (fakeForm) {
			param = {};
			param.title = aras.getResource('', 'search.set_parameter_value');
			param.formNd = fakeForm;
			param.item = fakeItem;
			param.itemTypeNd = fakeItemType.node;
			param.parametersArray = parametersArray;
			param.aras = aras;

			let width = aras.getItemProperty(fakeForm, 'width');
			let height = aras.getItemProperty(fakeForm, 'height');
			if (!width) {
				width = 300;
			}
			if (!height) {
				height = 400;
			}
			param.dialogWidth = width;
			param.dialogHeight = height;
			param.resizable = true;
			param.content = 'ShowFormAsADialog.html';
		}
	}
	return param;
};

SearchParameterizedHelper.prototype.showSearchForm = function(searchAml, isForProjectTree, callback, param) {
	const win = aras.getMostTopWindowWithAras(window);
	win.ArasModules.Dialog.show('iframe', param).promise.then(
		function(resultItem) {
			if (!resultItem) {
				return undefined;
			}

			let resultValue;
			let i;
			let dataType;

			for (i = 0; i < param.parametersArray.length; i++) {
				const parameter = param.parametersArray[i];
				if (!parameter) {
					continue;
				}

				regExp = new RegExp('@\\{' + i + '\\}', 'g');
				resultValue = aras.getItemProperty(resultItem, parameter.propertyItem.getProperty('name'));

				if (isForProjectTree) {
					dataType = parameter.propertyItem.getProperty('data_type');
					if (dataType === 'string' || dataType === 'text' || dataType === 'ml_string') {
						resultValue = resultValue.replace(/\*/g, '%');
					}
				}

				searchAml = searchAml.replace(regExp, resultValue);

				if (isForProjectTree) {
					regExp = new RegExp('@\\{' + i + ',text="[^"]*"\\}', 'g');
					searchAml = searchAml.replace(regExp, resultValue);
				}
			}
			callback(searchAml);
		}
	);
};

/** search_mode.js **/
// (c) Copyright by Aras Corporation, 2008-2009.

function SearchMode(searchContainer, aras) {
	/// <summary>
	/// This class provides interface and some basic functionality to create search modes.
	/// To create your own search mode inherit from SearchMode class and implement required UI.
	/// </summary>
	/// <remarks>
	/// <p>
	/// Innovator client sends AML requests to server to get data.
	/// End users may not know about AML. They'd like to use some user friendly UI.
	/// </p>
	/// <p>
	/// <h2 class="heading">Important</h2>
	/// The only purpose of any Search Mode is build AML query.
	/// That also provides some UI to do this.
	/// It is important to understand that Search Mode doesn't send the built AML query to server.
	/// </p>
	/// </remarks>
	/// <param name="searchContainer" type="Aras.Client.JS.SearchContainer" mayBeNull="false">
	/// Instance of Aras.Client.JS.SearchContainer class.
	/// </param>
	/// <param name="aras" type="Aras">
	/// Instance of Aras class
	/// </param>
	/// <example>
	/// <code language="JavaScript">
	///   function MySearchMode()
	///   {
	///   }
	///   MySearchMode.prototype = new SearchMode();
	///
	///   //your own onStartSearchMode implementation
	///   MySearchMode.prototype.onStartSearchMode = function MySearchMode_onStartSearchMode(sContainer)
	///   {
	///     // Call base onStartSearchMode method.
	///     SearchMode.prototype.onStartSearchMode.call(this, sContainer);
	///
	///     if (this.toolbar &amp;&amp; this.toolbar.IsButtonVisible("add_criteria"))
	///       toolbar.HideItem("add_criteria");
	///   }
	///
	///   //...
	///
	///   searchMode = new MySearchMode();// this is obligatory line. searchMode is predefined global variable.
	/// </code>
	/// </example>

	// ************************************* Privileged SearchMode members *************************************
	this._initCurrentQueryItem = function() {
		this.currQryItem = this.aras.newQryItem(this.searchContainer.itemTypeName);
		this.currQryItem.setPage(1);
	};

	this._getDatePattern = function(query_type) {
		var propName;
		switch (query_type) {
			case 'Released': propName = 'release_date';
				break;
			case 'Effective': propName = 'effective_date';
				break;
			case 'Latest':
				break;
			default: propName = 'modified_on';
				break;
		}

		var currItemType = this.aras.getItemTypeDictionary(this.currQryItem.itemTypeName).node;
		var ptrn = this.aras.getItemProperty(currItemType.selectSingleNode('Relationships/Item[@type=\'Property\' and name=\'' + propName + '\']'), 'pattern');
		if (!ptrn) {
			ptrn = 'short_date_time';
		}
		return this.aras.getDotNetDatePattern(ptrn);
	};

	this._getStartEndOfDay = function(r, isEnd) {
		r = this.aras.convertToNeutral(r, 'date', this.aras.getDotNetDatePattern('short_date_time'));
		r = r.substr(0, 4) + '-' + r.substr(5, 2) + '-' + r.substr(8, 2) + (!isEnd ? 'T00:00:00' : 'T23:59:59');
		return r;
	};

	this._createItemByXPath = function(itemXPath) {
		var isAppend = (this.aras.getPreferenceItemProperty('Core_GlobalLayout', null, 'core_append_items') == 'true');

		var arr = this._parseXPath(itemXPath);
		var currNd = null;
		var createNewTag = false;
		for (var i = 0; i < arr.length; i++) {
			var tagInfo = arr[i];
			var tagNm = tagInfo.tag;
			var itType = (tagNm == 'Item' && tagInfo.attributes && tagInfo.attributes.type ? tagInfo.attributes.type : '');

			var x = tagNm;
			if (itType) {
				x += '[@type=\'' + itType + '\']';
			}

			var t = null;
			if (!currNd) {
				t = this.currQryItem.dom.selectSingleNode(x);
			} else {
				t = currNd.selectSingleNode(x);
			}

			if (!t) {
				var newNd = currNd.ownerDocument.createElement(tagNm);

				if (tagNm == 'Item') {
					if (itType) {
						newNd.setAttribute('type', itType);
					}
					newNd.setAttribute('action', 'get');
				}

				currNd = currNd.appendChild(newNd);
			} else {
				if (isAppend && arr.length > 0 && i == arr.length - 1) {
					currNd = t.parentNode.appendChild(t.cloneNode(false));
				} else {
					currNd = t;
				}
			}
		}

		return currNd;
	};

	this._parseXPath = function(xpath) {
		var resArr = [];
		if (!xpath) {
			return resArr;
		}

		var arr = xpath.split('/');
		var re = /Item(?:\[[^\[\]]*\])*\[@type=['"]([\w ]+)["']\](?:\[[^\[\]]*\])*/; //Item tag with @type criteria
		var re2 = /([^\[\]]+)(?:\[[^\[\]]*\])*(?:\[[^\[\]]*\])*/; //tag name with criteria

		for (var i = 0; i < arr.length; i++) {
			var t = arr[i];
			if (t == '.') {
				continue;
			}
			if (t == '..') {
				resArr.pop();
				continue;
			}

			var e = {};
			if (re.test(t)) {
				e.tag = 'Item';
				e.attributes = {};
				e.attributes.type = RegExp.$1;
			} else if (re2.test(t)) {
				e.tag = RegExp.$1;
			} else {
				e.tag = t;
			}

			resArr.push(e);
		}

		return resArr;
	};

	this._setPaginationValuesToCurrQryItem = function() {
		if (!this.pagination) {
			return;
		}

		const setPageSize = (function(newPageSize, currentQueryPageSize) {
			this.setPageSize(newPageSize);

			newPageSize = newPageSize ? newPageSize.toString() : '';
			if (('' === newPageSize && '-1' !== currentQueryPageSize) || (currentQueryPageSize !== newPageSize)) {
				this.setPageNumber(1);
				return false;
			}
			return true;
		}).bind(this);

		const setMaxResults = (function(newMaxResults, currentQueryMaxResults) {
			if (this.pagination.getItem('pagination_max_results').hidden) {
				return true;
			}

			this.setMaxRecords(newMaxResults);

			newMaxResults = newMaxResults ? newMaxResults.toString() : '';
			if ('' === newMaxResults && '-1' === currentQueryMaxResults) {
			} else if (currentQueryMaxResults !== newMaxResults) {
				this.setPageNumber(1);
				return false;
			}
			return true;
		}).bind(this);

		const pageSizeValue = this.pagination.pageSize;
		const maxResultsValue = this.pagination.maxResults;
		const currentPageNumber = this.pagination.currentPageNumber;
		const updatePageNumberAfterSetPageSize = setPageSize(pageSizeValue, this.getPageSize());
		const updatePageNumberAfterSetMaxResults = setMaxResults(maxResultsValue, this.getMaxRecords());

		if (updatePageNumberAfterSetPageSize && updatePageNumberAfterSetMaxResults) {
			this.setPageNumber(currentPageNumber);
		}
	};
	this._setQueryControlsValuesToCurrQryItem = function() {
		if (!this.searchToolbar) {
			return;
		}

		const queryTypeControl = this.searchToolbar.data.get('searchview.commandbar.default.querytype');
		if (!queryTypeControl) {
			return;
		}

		const queryType = queryTypeControl.value;
		if (queryType === 'Current') {
			this.currQryItem.removeItemAttribute('queryType');
			this.currQryItem.removeItemAttribute('queryDate');
		} else {
			this.currQryItem.setItemAttribute('queryType', queryType);

			const queryDateControl = this.searchToolbar.data.get('searchview.commandbar.default.querydate');
			let queryDateStr = queryDateControl.value;

			if (queryDateStr === this.aras.getResource('', 'itemsgrid.today') || queryDateStr === '') {
				queryDateStr = this.aras.parse2NeutralEndOfDayStr(new Date());
			} else {
				const tmpDt = queryDateStr;
				queryDateStr = this.aras.convertToNeutral(queryDateStr, 'date', this._getDatePattern(queryType));
				if (!queryDateStr || tmpDt === queryDateStr) {
					this.aras.AlertError(this.aras.getResource('', 'search.please_enter_valid_as_of_date'));
					queryDateControl.value = '';
					this.searchToolbar.data.set(queryDateControl.id, Object.assign({}, queryDateControl));
					this.searchToolbar.render();
					return;
				}
			}

			this.currQryItem.setItemAttribute('queryDate', queryDateStr);
		}
	};
	// ************************************* End of SearchMode SearchContainer members *************************************

	if (arguments.length === 0) {
		return;
	}

	this.aras = aras;
	this.searchContainer = searchContainer;
	this.grid = searchContainer.getGrid();
	this.toolbar = searchContainer.getToolbar();
	this.pagination = searchContainer.pagination;
	this.searchToolbar = searchContainer.searchToolbar;
	this.id = '';
	this.name = '';
	this.complexity = 0;
	this.amlValidator = null;
	this.domToValidateXML = this.aras.createXMLDocument();
	this._initCurrentQueryItem();
	this.cache = {};
}

//contains true when validation succeded and false when failed.
SearchMode.prototype.isValidAML = true;
//contains true when search mode supports xClass search
SearchMode.prototype.supportXClassSearch = false;

SearchMode.prototype.xClassSearchCriteriaXPath = './*[(translate(local-name(), "and", "AND")="AND" or translate(local-name(), "or", "OR")="OR"' +
	' or translate(local-name(), "not", "NOT")="NOT") and @xClassSearchCriteria="1"]';

SearchMode.prototype.onStartSearchMode = function SearchModeOnStartSearchMode() {
	/// <summary>
	/// Method called when the search mode loaded into SearchContainer.
	/// </summary>
	/// <remarks>
	/// Can be used to perform search mode UI initialization.
	/// </remarks>
};

SearchMode.prototype.onEndSearchMode = function SearchModeOnEndSearchMode() {
	/// <summary>
	/// Method called on SearchContainer dispose or when SearchContainer hides current search mode and shows another.
	/// </summary>
	/// <remarks>The purpose of this method is to perform some actions on SearchMode remove/dispose.</remarks>
	this.searchContainer.setStyleAttribute('display', 'none');
};

SearchMode.prototype.testAmlForCompatibility = function SearchModeTestAmlForCompatibility(searchAml) {
	/// <summary>
	/// Tests AML for compatibility with current search mode.
	/// </summary>
	/// <remarks>
	/// Compatibility means that AML can be successfully parsed and displayed by search mode.
	/// </remarks>
	/// <param name="searchAml" type="string" mayBeNull="true">
	/// AML to test for compatibility.
	/// </param>
	/// <returns type="boolean">true if AML is compatible with current search mode, otherwise false.</returns>
	this.domToValidateXML.loadXML(searchAml);
	if (this.domToValidateXML.parseError.errorCode !== 0) {
		this.aras.AlertError(this.aras.getResource('', 'common.an_internal_error_has_occured'), this.aras.getResource('',
		'search.bad_xml', this.domToValidateXML.parseError.reason), this.aras.getResource('', 'common.client_side_err'));
		this.isValidAML = true;
		return false;
	}

	if (this.amlValidator && this.generateValidationInfo) {
		var xmlSchemaCache = null;
		var currItemType = this.aras.getItemTypeDictionary(this.currQryItem.itemTypeName);
		var key = this.aras.MetadataCache.CreateCacheKey('testAmlForCompatibility_xmlSchemaCache', this.name, currItemType.getId(),
		this.searchContainer.searchLocation, (this.aras.getVariable('SortPages') == 'true'));
		var cachedResult = this.aras.MetadataCache.GetItem(key);

		if (!cachedResult) {
			var validationInfoObject = this.generateValidationInfo();
			var xsdSchema = this.amlValidator.generateSchema(validationInfoObject);
			xmlSchemaCache = xsdSchema;
			var resultToCache = this.aras.IomFactory.CreateCacheableContainer(xsdSchema, currItemType.node);
			this.aras.MetadataCache.SetItem(key, resultToCache);
		} else {
			xmlSchemaCache = cachedResult.Content();
		}
		this.isValidAML = this.amlValidator.validate(searchAml, xmlSchemaCache);
		if (!this.isValidAML) {
			return this.isValidAML;
		}
	}

	return true;
};

SearchMode.prototype.setAml = function SearchModeSetAml(searchAML) {
	/// <summary>
	/// Initializes search mode with AML.
	/// </summary>
	/// <param name="searchAML" type="string" mayBeNull="true">AML to initialize search mode.</param>
	if (!SearchMode.prototype.testAmlForCompatibility.call(this, searchAML) && this.isValidAML) {
		return false;
	}

	this.currQryItem.loadXML(searchAML);
	this.currQryItem.setType(this.searchContainer.itemTypeName);
};

SearchMode.prototype.clearSearchCriteria = function SearchModeClearSearchCriteria() {
	/// <summary>
	/// Removes all criterias from current query item.
	/// </summary>
	/// <remarks>
	/// Removes all items criterias and where attribute. Value for select attribute will be reset to default.Required property values will be applied to query.
	/// </remarks>

	this.currQryItem.removeAllCriterias();
	this.currQryItem.removeItemAttribute('where');
	this.currQryItem.removeItemAttribute('order_by');

	if (this.grid && this.grid.isInputRowVisible()) {
		this.grid.SetPaintEnabled(false);
		for (var i = 0, j = this.grid.GetColumnCount(); i < j; i++) {
			var cell = this.grid.cells('input_row', i);
			if (cell.isEditable()) {
				cell.SetValue('');
			}
		}
		this.grid.SetPaintEnabled(true);
	}
};

SearchMode.prototype.getAml = function SearchModeGetAml() {
	/// <summary>
	/// Gets AML generated by search mode.
	/// </summary>
	/// <returns type="string">AML built by Search Mode.</returns>
	this._setPaginationValuesToCurrQryItem();

	const doc = XmlDocument();
	const useWildcards = this.aras.getPreferenceItemProperty('Core_GlobalLayout', null, 'core_use_wildcards') === 'true';
	let value;
	let criteria;
	let requiredPropertiesString = '';

	for (let propName in this.searchContainer.requiredProperties) {
		criteria = this.currQryItem.item.selectSingleNode(propName);
		if (!criteria) {
			value = this.searchContainer.requiredProperties[propName];
			criteria = doc.createElement(propName);
			criteria.text = value;
			criteria.setAttribute('condition', ((useWildcards && /[%|*]/.test(value)) ? 'like' : 'eq'));
			requiredPropertiesString += criteria.xml;
		}
	}
	if (ArasModules.utils.hashFromString(this.currQryItem.getCriteriesString() + requiredPropertiesString) !== this.getCacheItem('criteriesHash')) {
		this.removeCacheItem('itemmax');
		this.removeCacheItem('pagemax');
		this.removeCacheItem('criteriesHash');
	}
	if ((this.getCacheItem('itemmax') && this.getCacheItem('pagemax')) || this.searchContainer._isNoCountModeForCurrentItemType()) {
		this.setReturnMode('itemsOnly');
	} else {
		this.setReturnMode('countAndItems');
	}

	this._setQueryControlsValuesToCurrQryItem();

	return this.currQryItem.item.xml;
};

SearchMode.prototype.getPageNumber = function SearchModeGetPageNumber() {
	/// <summary>
	/// Gets page attribute for current query item.
	/// </summary>
	/// <returns type="Number" integer="true">Current page set in criteria. -1 will be returned if nothing specified.</returns>
	var page = this.currQryItem.getPage();
	if (!page) {
		page = -1;
	}
	return page;
};

SearchMode.prototype.setPageNumber = function SearchModeSetPageNumber(page) {
	/// <summary>
	/// Sets page attribute for current query item.
	/// </summary>
	/// <param name="page" type="Number" integer="true">Will have affect only if page size specified.</param>
	/// <remarks>Value should be a positive integer. In couple with page size allows arbitrary item selections.</remarks>
	/// <returns type="boolean">true if page was successfully set; false otherwise.</returns>
	if ('' === page || this.aras.isPositiveInteger(page)) {
		this.currQryItem.setPage(page);
		if (this.pagination) {
			this.pagination.currentPageNumber = page;
		}
		return true;
	} else {
		this.aras.AlertError(this.aras.getResource('', 'search.page_should_positive_integer'), '', '', window);
		return false;
	}
};

SearchMode.prototype.getPageSize = function SearchModeGetPageSize() {
	/// <summary>
	/// Gets pagesize attribute for current query item.
	/// </summary>
	/// <returns type="Number" integer="true">Current pagesize set in criteria. -1 will be returned if nothing specified.</returns>
	return this.currQryItem.getPageSize();
};

SearchMode.prototype.setPageSize = function SearchModeSetPageSize(pageSize) {
	/// <summary>
	/// Sets pagesize attribute for current query item.
	/// </summary>
	/// <param name="pageSize" type="Number" integer="true">Number of items per page to select.</param>
	/// <remarks>Value should be a positive integer.</remarks>
	/// <returns type="boolean">true if page size was successfully set; false otherwise.</returns>
	if (this.pagination) {
		this.currQryItem.setPageSize(pageSize || '');
		this.pagination.pageSize = pageSize;

		return true;
	}

	if ('' === pageSize || this.aras.isPositiveInteger(pageSize)) {
		this.currQryItem.setPageSize(pageSize);
		return true;
	} else {
		this.aras.AlertError(this.aras.getResource('', 'search.page_size_should_positive_integer'), '', '', window);
		return false;
	}
};

SearchMode.prototype.getMaxRecords = function SearchModeGetMaxRecords() {
	/// <summary>
	/// Gets maxRecords attribute for current query item.
	/// </summary>
	/// <returns type="Number" integer="true">Current maxRecords set in criteria. -1 will be returned if nothing specified.</returns>
	return this.currQryItem.getMaxRecords();
};

SearchMode.prototype.setMaxRecords = function SearchModeSetMaxRecords(maxRecords) {
	/// <summary>
	/// Sets maxRecords attribute for current query item.
	/// </summary>
	/// <param name="maxRecords" type="Number" integer="true">The maximum number of items to retrieve.</param>
	/// <remarks>Value should be a positive integer.</remarks>
	/// <returns type="boolean">true if maxRecords was successfully set; false otherwise.</returns>
	if (this.pagination) {
		this.currQryItem.setMaxRecords(maxRecords || '');
		this.pagination.maxResults = maxRecords;

		return true;
	}

	if ('' === maxRecords || this.aras.isPositiveInteger(maxRecords)) {
		this.currQryItem.setMaxRecords(maxRecords);
		return true;
	} else {
		this.aras.AlertError(this.aras.getResource('', 'search.max_search_value_should_positive_integer'), '', '', window);
		return false;
	}
};

SearchMode.prototype.setReturnMode = function SearchModeSetReturnMode(returnMode) {
	/// <summary>
	/// Sets returnMode attribute for current query item.
	/// </summary>
	/// <param name="returnMode" type="string">The value is considered to be a hint to the server to identify type of returned data.</param>
	this.currQryItem.setReturnMode(returnMode);
};

SearchMode.prototype.getOrderBy = function SearchModeGetOrderBy() {
	/// <summary>
	/// Gets order_by attribute for current query item.
	/// </summary>
	/// <returns type="string">Value of the order_by attribute.</returns>
	return this.currQryItem.getOrderBy();
};

SearchMode.prototype.setOrderBy = function SearchModeSetOrderBy(orderBy) {
	/// <summary>
	/// Sets order_by attribute for current query item.
	/// </summary>
	/// <param name="orderBy" type="string">
	/// You can sort query results by one or more of the properties in the returned items by using an order_by attribute.
	/// </param>
	/// <remarks>Supports the keywords ASC (ascending) and DESC (descending).</remarks>
	this.currQryItem.setOrderBy(orderBy);
	return true;
};

SearchMode.prototype.getSelect = function SearchModeGetSelect() {
	/// <summary>
	/// Gets select attribute for current query item.
	/// </summary>
	/// <remarks>Select attribute contains list of item properties to select.</remarks>
	/// <returns type="string">Value of the select attribute.</returns>
	return this.currQryItem.getSelect();
};

SearchMode.prototype.setSelect = function SearchModeSetSelect(selectAttr) {
	/// <summary>
	/// Sets select attribute for current query item.
	/// </summary>
	/// <param name="selectAttr" type="string">List of properties names divided by comma.</param>
	this.currQryItem.setSelect(selectAttr);
};

SearchMode.prototype.getCacheItem = function SearchModeGetCacheItem(key) {
	/// <summary>
	/// Gets item from cache for current search mode.
	/// </summary>
	/// <param name="key" type="string">Key for access to cache item.</param>
	/// <remarks>Cache using for storage itemmax and pagemax values.</remarks>
	/// <returns type="any">Value of the cache item.</returns>
	return this.cache[key];
};

SearchMode.prototype.setCacheItem = function SearchModeSetCacheItem(key, value) {
	/// <summary>
	/// Sets item to cache for current search mode.
	/// </summary>
	/// <param name="key" type="string">Key for access to cache item.</param>
	/// <param name="value" type="any">Value of cache item.</param>
	this.cache[key] = value;
};

SearchMode.prototype.removeCacheItem = function SearchModeRemoveCacheItem(key) {
	/// <summary>
	/// Delete item from cache for current search mode.
	/// </summary>
	/// <param name="key" type="string">Key for access to cache item.</param>
	delete this.cache[key];
};
/*@cc_on
@if (@register_classes == 1)
Type.registerNamespace("Aras");
Type.registerNamespace("Aras.Client");
Type.registerNamespace("Aras.Client.JS");

Aras.Client.JS.SearchMode = SearchMode;
Aras.Client.JS.SearchMode.registerClass("Aras.Client.JS.SearchMode");
@end
@*/

/** ..\BrowserCode\common\javascript\XmlHttpRequestManagerCommon.js **/
function XmlRequestImplementation() {
	this.xhr = new XMLHttpRequest();
	this.headers = {};
}

XmlRequestImplementation.prototype.open = function(method, url, isAsync) {
	isAsync = (isAsync === 1 || isAsync === true);
	this.xhr.open(method, url, isAsync);
};

Object.defineProperty(XmlRequestImplementation.prototype, 'onreadystatechange', {
	set: function(value) {
		this.xhr.onreadystatechange = value;
	}
});

XmlRequestImplementation.prototype.setRequestHeader = function(name, value) {
	this.headers[name] = value;
};

XmlRequestImplementation.prototype.send = function(body) {
	for (var key in this.headers) {
		if (this.headers.hasOwnProperty(key)) {
			this.xhr.setRequestHeader(key, this.headers[key]);
		}
	}
	//this line is required for IE 10.
	try { this.xhr.responseType = 'msxml-document'; } catch (e) { }
	this.xhr.send(body);
};

XmlRequestImplementation.prototype.getResponseHeader = function(header) {
	return this.xhr.getResponseHeader(header);
};

XmlRequestImplementation.prototype.getAllResponseHeaders = function() {
	return this.xhr.getAllResponseHeaders();
};

Object.defineProperty(XmlRequestImplementation.prototype, 'readyState', {
	get: function() {
		return this.xhr.readyState;
	}
});

Object.defineProperty(XmlRequestImplementation.prototype, 'status', {
	get: function() {
		return this.xhr.status;
	}
});

Object.defineProperty(XmlRequestImplementation.prototype, 'responseText', {
	get: function() {
		return this.xhr.responseText;
	}
});

Object.defineProperty(XmlRequestImplementation.prototype, 'responseXML', {
	get: function() {
		return this.xhr.responseXML;
	}
});

function XmlHttpRequestManager() {
}

XmlHttpRequestManager.prototype.CreateRequest = function() {
	return new XmlRequestImplementation();
};

/** ..\BrowserCode\common\javascript\XmlDocument.js **/
function XmlDocument() {
	var xmlDoc;
	if (window.ActiveXObject !== undefined) {
		xmlDoc = new ActiveXObject('Msxml2.FreeThreadedDOMDocument.6.0');
		xmlDoc.setProperty('AllowXsltScript', true);
		xmlDoc.async = false;
		xmlDoc.preserveWhiteSpace = true;
		xmlDoc.validateOnParse = false;
	} else {
		xmlDoc = document.implementation.createDocument('', '', null);
		xmlDoc.async = false;
		xmlDoc.preserveWhiteSpace = true;
	}
	return xmlDoc;
}

/** ..\BrowserCode\common\javascript\XmlDocumentCommon.js **/
Document.prototype.loadXML = function XmlDocumentLoadXML(xmlString) {
	if (!xmlString || typeof (xmlString) !== 'string') {
		return false;
	}
	xmlString = xmlString.replace(/xmlns:i18n="http:\/\/www.w3.org\/XML\/1998\/namespace"/g, 'xmlns:i18n="http://www.aras.com/I18N"');
	var parser = new DOMParser();
	var doc = parser.parseFromString(xmlString, 'text/xml');
	if (!this.documentElement) {
		this.appendChild(this.createElement('oldTeg'));
	}

	this.replaceChild(doc.documentElement, this.documentElement);
	return (this.parseError.errorCode === 0);
};

Document.prototype.loadUrl = function XmlDocumentLoadUrl(filename) {
	if (!filename || typeof (filename) !== 'string') {
		return;
	}
	if (window.ActiveXObject) {
		xhttp = new ActiveXObject('Msxml2.XMLHTTP');
	} else {
		xhttp = new XMLHttpRequest();
	}
	xhttp.open('GET', filename, false);
	try { xhttp.responseType = 'msxml-document'; } catch (err) { } // Helping IE11
	xhttp.send('');
	this.loadXML(xhttp.response);
};

Document.prototype.selectSingleNode = function XmlDocumentSelectSingleNode(xPath) {
	var xpe = new XPathEvaluator();
	var ownerDoc = this.ownerDocument == null ? this.documentElement : this.ownerDocument.documentElement;
	var nsResolver = xpe.createNSResolver(ownerDoc == null ? this : ownerDoc);

	return xpe.evaluate(xPath, this, nsResolver, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
};
Element.prototype.selectSingleNode = Document.prototype.selectSingleNode;

Document.prototype.selectNodes = function XmlDocumentSelectNodes(xPath) {
	var xpe = new XPathEvaluator();
	var ownerDoc = this.ownerDocument == null ? this.documentElement : this.ownerDocument.documentElement;
	var nsResolver = xpe.createNSResolver(ownerDoc == null ? this : ownerDoc);

	var result = xpe.evaluate(xPath, this, nsResolver, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
	var res = null;
	if (result) {
		res = [];
		for (var i = 0; i < result.snapshotLength; i++) {
			res.push(result.snapshotItem(i));
		}
	}
	return res;
};
Element.prototype.selectNodes = Document.prototype.selectNodes;

Element.prototype.transformNode = function XmlElementTransformNode(xmlDoc) {
	var outputNode = xmlDoc.selectSingleNode('./xsl:stylesheet/xsl:output');
	var isHtml = (outputNode && outputNode.getAttribute('method') === 'html');
	var sourceDoc = document.implementation.createDocument('', '', null);
	var node = sourceDoc.importNode(this, true);
	sourceDoc.appendChild(node);
	var processor = new XSLTProcessor();
	processor.importStylesheet(xmlDoc);
	var resultDoc = processor.transformToDocument(sourceDoc);
	//Microsoft Edge might not properly pefrom transfomration of XML document and we will have 'null' after transfomration.
	//In this case we should return an error message instead of 'null'. The error message corresponds to Chrome error message
	if (!resultDoc) {
		return '<html xmlns=\'http://www.w3.org/1999/xhtml\'><body><parsererror><h3>This page contains the following errors:</h3>' +
				'<div>Document parsing error</div></parsererror></body></html>';
	}
	return isHtml ? resultDoc.documentElement.outerHTML : resultDoc.xml;
};

Document.prototype.transformNode = function XmlDocumentTransformNode(xmlDoc) {
	//In Microsoft Edge when xmlDoc created in other window it's not instance of XMLDocument
	//So we need to create new instance to avoid 'null' after transformToDocument
	if (!(xmlDoc instanceof XMLDocument)) {
		var oldXml = xmlDoc.xml;
		xmlDoc = new XmlDocument();
		xmlDoc.loadXML(oldXml);
	}
	var processor = new XSLTProcessor();
	processor.importStylesheet(xmlDoc);
	var outputNode = xmlDoc.selectSingleNode('./xsl:stylesheet/xsl:output');
	var isHtml = (outputNode && outputNode.getAttribute('method') === 'html');
	var resultDoc = processor.transformToDocument(this);
	//Microsoft Edge might not properly pefrom transfomration of XML document and we will have 'null' after transfomration.
	//In this case we should return an error message instead of 'null'. The error message corresponds to Chrome error message
	if (!resultDoc) {
		return '<html xmlns=\'http://www.w3.org/1999/xhtml\'><body><parsererror><h3>This page contains the following errors:</h3>' +
				'<div>Document parsing error</div></parsererror></body></html>';
	}
	return isHtml ? resultDoc.documentElement.outerHTML : resultDoc.xml;
};

Document.prototype.createNode = function XmlDocumentTransformNode(nodeType, name, namespaceUrl) {
	var newNode = this.createElementNS(namespaceUrl, name);
	return newNode;
};

if (Document.prototype.__defineGetter__) {
	Document.prototype.__defineGetter__('text', function() {
		return this.textContent;
	});

	Document.prototype.__defineSetter__('text', function(value) {
		this.textContent = value;
	});

	Element.prototype.__defineGetter__('text', function() {
		return this.textContent;
	});

	Element.prototype.__defineSetter__('text', function(value) {
		this.textContent = value;
	});

	Text.prototype.__defineGetter__('text', function() {
		return this.textContent;
	});

	Attr.prototype.__defineGetter__('text', function(value) {
		return this.textContent;
	});

	Document.prototype.__defineGetter__('xml', function() {
		return (new XMLSerializer()).serializeToString(this);
	});

	Element.prototype.__defineGetter__('xml', function() {
		return (new XMLSerializer()).serializeToString(this);
	});

	Document.prototype.__defineGetter__('parseError', function() {
		if (!this.documentElement) {
			return {errorCode: 0};
		}

		//for Chrome browser that return html instead parsererror xml block
		var node = this.documentElement;
		if (node.nodeName === 'html' && node.firstChild && node.firstChild.firstChild) {
			node = node.firstChild.firstChild;
			if (node.nodeName === 'parsererror') {
				return {
					errorCode: 1,
					srcText: '',
					reason: node.childNodes[1].textContent
				};
			}
		}

		if (this.documentElement.nodeName == 'parsererror') {
			return {
				errorCode: 1,
				srcText: '',
				reason: this.documentElement.childNodes[0].nodeValue
			};
		}

		return {errorCode: 0};
	});
}

XMLDocument.prototype.load = function(docUrl) {
	var xmlhttp = new XmlHttpRequestManager().CreateRequest();
	xmlhttp.open('GET', docUrl, false);
	xmlhttp.send(null);
	this.loadXML(xmlhttp.responseText);
};

/** MLDialogHelper.js **/
function MLDialogHelper() {
}

MLDialogHelper.prototype._newItem = function MLDialogHelper_newItem(type, action) {
	if (typeof Item === 'undefined') {
		return new parent.Item(type, action);
	}
	return new Item(type, action);
};

MLDialogHelper.prototype.show = function MLDialogHelper_show(win, aras, itemNd, mlPropertyInfo, isReadOnly, callback) {
	//possible return values
	//undefined. If user closes dialog without changes.
	//null. If user selects "Set Nothing"
	//AML string. "Fake Item AML" with entered properties.
	var mlPropertyName = mlPropertyInfo.name;

	var fillFakeItem = function(itemNd, fakeItem, langs, mlPropertyName) {
		var val, langCode, sessionLangCode = aras.getSessionContextLanguageCode(), sessionLangIndex;
		//perhaps it would be better to compare langs.length and number of translations on a client side. In case of new item
		//there may be redundant request to server. Needs investigation.

		var i18nNodes = [],
			getItemTranslationCallback = function(foundNode) {
				if (foundNode) {
					i18nNodes.push(foundNode);
					fakeItem.setProperty('fake_property_' + i, foundNode.text);
				}
			};
		for (var i = 0; i < langs.length; i++) {
			langCode = aras.getItemProperty(langs[i], 'code');
			if (langCode === sessionLangCode) {
				sessionLangIndex = i;
			}
			aras.getItemTranslation(itemNd, mlPropertyName, langCode, null, getItemTranslationCallback);
		}

		if (i18nNodes.length != langs.length) {
			var itmNd = aras.getItemFromServer(itemNd.getAttribute('type'), itemNd.getAttribute('id'), mlPropertyName, false, '*').node;
			if (itmNd) {
				for (var j = 0; j < langs.length; j++) {
					langCode = aras.getItemProperty(langs[j], 'code');
					val = aras.getItemTranslation(itmNd, mlPropertyName, langCode, '');
					fakeItem.setProperty('fake_property_' + j, val);
				}
			}
		}
		fakeItem.setProperty('fake_property_' + sessionLangIndex, aras.getItemProperty(itemNd, mlPropertyName));
	};

	var fakeForm = this._newItem('Form', ''), fakeField, fakeFormBody, fakeItemType = this._newItem('ItemType', ''), fakeProperty, fakeItem;
	fakeForm.setID('349CD00F696A419EB1CF5812AE7FF5EA');
	fakeForm.setProperty('name', 'fake_MLDialog_349CD00F696A419EB1CF5812AE7FF5EA');
	fakeForm.setProperty('stylesheet', '../styles/default.css');
	fakeFormBody = this._newItem('Body', '');
	fakeForm.addRelationship(fakeFormBody);
	fakeField = this._newItem('Field', '');
	fakeField.setID('fakeHtml_45A45476CCFE4836AC1F2A5AC94D75E1');
	fakeField.setProperty('field_type', 'html');
	fakeField.setProperty('sort_order', '0');
	fakeField.setProperty('x', '0');
	fakeField.setProperty('y', '0');
	fakeField.setProperty('name', 'fake_field_html');
	fakeField.setProperty('html_code', '<script src="../javascript/MLDialog.js"></' + 'script>');
	fakeFormBody.addRelationship(fakeField);

	fakeItemType.setID('5901A03E806B47DA87BC7D4DA6527975');
	fakeItemType.setProperty('name', 'fake_MLDialog_5901A03E806B47DA87BC7D4DA6527975');
	fakeItem = this._newItem(fakeItemType.getProperty('name'), 'add');

	var getLanguagesResultNd = aras.getLanguagesResultNd();
	var langNd, langNds = getLanguagesResultNd.selectNodes('Item[@type=\'Language\']'), lastModifiedOn = '', tmp,
		displayLength = Math.min(parseInt(19 + 4.74 * (mlPropertyInfo.stored_length ? mlPropertyInfo.stored_length : '40')), 1000);
	for (var i = 0; i < langNds.length; i++) {
		langNd = langNds[i];
		tmp = aras.getItemProperty(langNd, 'modified_on');
		if (!tmp) {
			throw new Error('modified_on of language is not specified');
		}
		if (tmp > lastModifiedOn) {
			lastModifiedOn = tmp;
		}
		fakeProperty = this._newItem('Property', '');
		fakeProperty.setID('fake' + i + '_DC0BE44F68724EE3A4F96A709C9B9121');
		fakeProperty.setProperty('data_type', 'string');
		fakeProperty.setProperty('stored_length', mlPropertyInfo.stored_length ? mlPropertyInfo.stored_length : '40');
		fakeProperty.setProperty('name', 'fake_property_' + i);
		fakeProperty.setProperty('pattern', mlPropertyInfo.pattern ? mlPropertyInfo.pattern : '');
		fakeItemType.addRelationship(fakeProperty);

		fakeField = this._newItem('Field', '');
		fakeField.setID('fake' + i + '_45A45476CCFE4836AC1F2A5AC94D75E1');
		fakeField.setProperty('display_length', displayLength);
		fakeField.setProperty('display_length_unit', 'px');
		fakeField.setProperty('field_type', 'text');
		fakeField.setProperty('font_color', '#000000');
		fakeField.setProperty('font_family', 'arial, helvetica, sans-serif');
		fakeField.setProperty('font_size', '8pt');
		fakeField.setProperty('font_weight', 'bold');

		fakeField.setProperty('is_visible', '1');
		fakeField.setProperty('label', aras.getItemProperty(langNd, 'name'));
		fakeField.setProperty('label_position', 'top');
		fakeField.setProperty('propertytype_id', fakeProperty.getID('id'));
		fakeField.setProperty('sort_order', i);
		fakeField.setProperty('tab_index', i + 1000);
		fakeField.setProperty('x', '40');
		fakeField.setProperty('y', 40 + i * 40);
		fakeField.setProperty('name', 'fake_field_' + i);
		fakeFormBody.addRelationship(fakeField);
	}

	//to make dialog generated html properly cached
	fakeItemType.setProperty('modified_on', lastModifiedOn);
	fakeForm.setProperty('modified_on', lastModifiedOn);

	fillFakeItem(itemNd, fakeItem, langNds, mlPropertyName);

	var param = {
		title: aras.getResource('', 'mldialog.ml_entry'),
		formNd: fakeForm.node,
		itemTypeNd: fakeItemType.node,
		aras: aras,
		formType: isReadOnly ? 'view' : 'edit',
		item: fakeItem,
		dialogWidth: displayLength + 2 * 40 + 2 * 7 /*paddings*/,
		dialogHeight: langNds.length * 40 + 2 * 40,
		resizable: true,
		content: 'ShowFormAsADialog.html',
		type: 'Multilingual'
	};

	win.ArasModules.Dialog.show('iframe', param).promise.then(callback);
};

MLDialogHelper.prototype.updateItemByShowResult = function MLDialogHelper_updateItemByShowResult(aras, itemNd, mlPropertyName, showResult) {
	//returns true if filled
	if (showResult === undefined) {
		return false;
	}
	if (!showResult) {
		showResult = '<Item/>';
	}
	var fakeItem = this._newItem('Tmp', '');
	fakeItem.loadAML(showResult);

	var val, langCode, sessionLangCode = aras.getSessionContextLanguageCode();
	var getLanguagesResultNd = aras.getLanguagesResultNd();
	var langNds = getLanguagesResultNd.selectNodes('Item[@type=\'Language\']');

	for (var i = 0; i < langNds.length; i++) {
		langCode = aras.getItemProperty(langNds[i], 'code');
		val = fakeItem.getProperty('fake_property_' + i) || null;
		if (langCode === sessionLangCode) {
			aras.setItemProperty(itemNd, mlPropertyName, val || '', this._applyToCachedItems());
		}
		aras.setItemTranslation(itemNd, mlPropertyName, val, langCode);
	}
	return true;
};

MLDialogHelper.prototype._applyToCachedItems = function MLDialogHelper_applyToCachedItems() {
	return document.applyChanges2All;
};

/** aml_validator.js **/
function AmlValidator(aras) {
	this.aras = aras;

	this.types = {};

	// XmlDocument that contains xslt transformation applied for each aml before validation.
	this.xslt = null;

	this.schemaGlobalObjects = [];

	this.xslt = this.aras.createXMLDocument();
	this.xslt.loadXML(
		'<?xml version="1.0" encoding="UTF-8"?>' +
		'<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">' +
		'  <xsl:output method="xml" version="1.0" encoding="UTF-8" indent="yes"/>' +
		'  <xsl:template match="/ | @* | node()">' +
		'    <xsl:choose>' +
		'      <xsl:when test="local-name() = \'OR\'">' +
		'        <xsl:call-template name="OR"/>' +
		'      </xsl:when>' +
		'      <xsl:when test="local-name() = \'NOT\'">' +
		'        <xsl:call-template name="NOT"/>' +
		'      </xsl:when>' +
		'      <xsl:when test="local-name() = \'Relationships\'">' +
		'        <xsl:call-template name="TransformRelationships"/>' +
		'      </xsl:when>' +
		'      <xsl:otherwise>' +
		'        <xsl:call-template name="doCopy"/>' +
		'      </xsl:otherwise>' +
		'    </xsl:choose>' +
		'  </xsl:template>' +
		'  <xsl:template name="NOT">' +
		'    <xsl:element name="NOT">' +
		'      <xsl:for-each select="*">' +
		'        <xsl:choose>' +
		'          <xsl:when test="local-name() = \'OR\'">' +
		'            <xsl:call-template name="OR"/>' +
		'          </xsl:when>' +
		'          <xsl:otherwise>' +
		'            <xsl:call-template name="doCopy"/>' +
		'          </xsl:otherwise>' +
		'        </xsl:choose>' +
		'      </xsl:for-each>' +
		'    </xsl:element>' +
		'  </xsl:template>' +
		'  <xsl:template name="OR">' +
		'    <xsl:variable name="firstNotORNode" select="*[local-name() != \'OR\']"/>' +
		'    <xsl:choose>' +
		'      <!-- ' +
		'      If OR contains not OR nodes. ' +
		'      1) Find first not OR node.' +
		'      2) Rename current OR node to OR-firstNotORNodeName.' +
		'      3) Rename all nested OR nodes to OR-firstNotORNodeName.' +
		'      -->' +
		'      <xsl:when test="count($firstNotORNode) > 0">' +
		'        <xsl:call-template name="createNewOR">' +
		'          <xsl:with-param name="newORName" select="local-name($firstNotORNode[1])"/>' +
		'        </xsl:call-template>' +
		'      </xsl:when>' +
		'      <!-- ' +
		'      Otherwise:' +
		'      1) If OR has OR child nodes, find the deepest OR node having not OR node element.' +
		'      2) If found such OR, rename it and all it"s parent OR nodes.' +
		'      3) If such OR not found, just copy structure.' +
		'      -->' +
		'      <xsl:when test="count(*[local-name() != \'OR\']) > 0">' +
		'        <xsl:call-template name="OR"/>' +
		'      </xsl:when>' +
		'      <xsl:otherwise>' +
		'        <xsl:call-template name="doCopy"/>' +
		'      </xsl:otherwise>' +
		'    </xsl:choose>' +
		'  </xsl:template>' +
		'  <xsl:template name="TransformRelationships">' +
		'    <xsl:element name="Relationships">' +
		'      <xsl:for-each select="*">' +
		'        <xsl:choose>' +
		'          <xsl:when test="local-name()=\'Item\'">' +
		'            <xsl:call-template name="createNewItem">' +
		'              <xsl:with-param name="newItemName" select="translate(@type, \' \', \'-\')"/>' +
		'            </xsl:call-template>' +
		'          </xsl:when>' +
		'          <xsl:otherwise>' +
		'            <xsl:call-template name="doCopy"/>' +
		'          </xsl:otherwise>' +
		'        </xsl:choose>' +
		'      </xsl:for-each>' +
		'    </xsl:element>' +
		'  </xsl:template>' +
		'  <xsl:template name="createNewItem">' +
		'    <xsl:param name="newItemName"/>' +
		'    <xsl:element name="Item-type-{$newItemName}-">' +
		'      <xsl:for-each select="@* | child::node()">' +
		'        <xsl:call-template name="doCopy"/>' +
		'      </xsl:for-each>' +
		'    </xsl:element>' +
		'  </xsl:template>' +
		'  <xsl:template name="createNewOR">' +
		'    <xsl:param name="newORName"/>' +
		'    <xsl:element name="OR-{$newORName}">' +
		'      <xsl:for-each select="child::node()">' +
		'       <xsl:choose>' +
		'          <xsl:when test="local-name(.) = \'OR\'">' +
		'            <xsl:call-template name="createNewOR">' +
		'              <xsl:with-param name="newORName" select="$newORName"/>' +
		'            </xsl:call-template>' +
		'          </xsl:when>' +
		'          <xsl:otherwise>' +
		'            <xsl:call-template name="doCopy"/>' +
		'          </xsl:otherwise>' +
		'        </xsl:choose>' +
		'      </xsl:for-each>' +
		'    </xsl:element>' +
		'  </xsl:template>' +
		'  <xsl:template name="doCopy">' +
		'    <xsl:copy>' +
		'      <xsl:apply-templates select="@* | node()"/>' +
		'    </xsl:copy>' +
		'  </xsl:template>' +
		'</xsl:stylesheet>');

	this._transformAmlBeforeValidation = function(amlToValidate) {
		var xd = this.aras.createXMLDocument();
		xd.validateOnParse = true;

		xd.loadXML(amlToValidate);
		xd.loadXML(xd.transformNode(this.xslt));
		return xd.xml;
	};

	this._transformXPath = function(XPath) {
		return XPath.replace(/\W/g, '-').replace(/[-]{2,}/g, '-');
	};

	this._getTypeOfLastItemInXPath = function(XPath) {
		/// <summary>
		/// Gets type of last Item in the XPath.
		/// </summary>
		/// <param name="XPath" type="string">Any XPath. Expected xpath like Item[@type="A"]/prop_item/Item[@type="B"]</param>
		/// <returns type="string">Type of last Item in the XPath or null.</returns>
		var res = /[@type=[''|""]([\w| ]*)[''|""]]$/.exec(XPath);
		if (res !== null) {
			res = res[1];
		}

		return res;
	};

	this._generatePropertyOR = function(orName, propName, propDT) {
		var res = '';
		res += '  <xs:complexType name="' + orName + '">';
		res += '    <xs:choice maxOccurs="unbounded">';
		res += this._generatePropertyDefinition(propName, propDT);
		res += '      <xs:element name="OR-' + propName + '" type="' + orName + '"/>';
		res += '    </xs:choice>';
		res += '  </xs:complexType>';
		return res;
	};

	this._generatePropertyDefinition = function(propName, propDT) {
		return '<xs:element name="' + propName + '" type="CONST-' + propDT.replace(' ', '-') + '"/>';
	};
}

AmlValidator.prototype.getRootItemXPath = function AmlValidatorGetRootItemXPath() {
	var rootItemXPath = '';
	for (var XPath in this.validationInfoObject) {
		rootItemXPath = XPath.split('/')[0];
		break;
	}
	return rootItemXPath;
};

AmlValidator.prototype.validate = function AmlValidatorValidate(amlToValidate, xmlSchemaCache) {
	/// <summary>
	/// Performs run-time validation on the aml  using the XMLSchemaCache object.
	/// </summary>
	/// <param name="amlToValidate" type="string">Any XPath. Expected xpath like Item[@type="A"]/prop_item/Item[@type="B"]</param>
	/// <param name="xmlSchemaCache" type="Object">XMLSchemaCache object containing validation schema.</param>
	/// <returns type="string">Returns empty string if validation passed successfully. Otherwise returns error message string.</returns>
	if (!amlToValidate || !xmlSchemaCache) {
		return '';
	}
	var schemas = [];
	schemas.push({namespace: '', xml: xmlSchemaCache});
	var res = this.aras.ValidateXml(schemas, this._transformAmlBeforeValidation(amlToValidate));
	var isValid = res.selectSingleNode('Result/isvalid').text == 'true';
	if (!isValid) {
		//validation failed
		return false;
	} else {
		//validation passed
		return true;
	}
};

AmlValidator.prototype.generateItemDefinition = function AmlValidatorGenerateItemDefinition(parentItemXPath, isRoot, withKeyedName) {
	if (!parentItemXPath) {
		return '';
	}

	var typeOfItem = this._getTypeOfLastItemInXPath(parentItemXPath);

	var newItemTagName = 'Item';
	var parentItemXPathSplitted = parentItemXPath.split('/');
	if (parentItemXPathSplitted.length > 2 && 'Relationships' == parentItemXPathSplitted[parentItemXPathSplitted.length - 2]) {
		newItemTagName = this._transformXPath(parentItemXPathSplitted[parentItemXPathSplitted.length - 1]);
	}

	var itemDefinition = [];
	itemDefinition.push('  <xs:element name="' + newItemTagName + '">');
	itemDefinition.push('    <xs:complexType>');

	this.generateInnerItemDefinition(parentItemXPath, itemDefinition, withKeyedName);
	this.generateItemAttributesDefinition(typeOfItem, itemDefinition, isRoot);

	itemDefinition.push('    </xs:complexType>');
	itemDefinition.push('  </xs:element>');

	return itemDefinition.join('');
};

AmlValidator.prototype.generateDefinitionForNotGroup = function AmlValidatorGenerateDefinitionForNotGroup(parentItemXPath, parentItemDef, withKeyedName) {
	var transformedParentItemXPath = this._transformXPath(parentItemXPath);

	var orGroupName = 'OR-Group-' + transformedParentItemXPath;
	var nameOfNotDefinition = 'NOT-' + transformedParentItemXPath;

	var groupDefinition = [];
	groupDefinition.push('<xs:complexType name="' + nameOfNotDefinition + '">');
	groupDefinition.push('  <xs:choice maxOccurs="unbounded">');
	groupDefinition.push('    <xs:group ref="' + orGroupName + '" maxOccurs="unbounded"/>');

	if (withKeyedName) {
		groupDefinition.push('    <xs:element name="keyed_name" type="CONST-string"/>');
	}

	var parentItemXPathDeep = parentItemXPath.split('/').length;

	for (var currentXPath in this.validationInfoObject) {
		if (currentXPath.indexOf(parentItemXPath) == -1) {
			continue;
		}

		var currentXPathArray = currentXPath.split('/');
		var currentXPathDeep = currentXPathArray.length;
		if (currentXPathDeep == parentItemXPathDeep + 1) {
			var propDef = this.validationInfoObject[currentXPath];
			var realPropDef = this.aras.getRealPropertyForForeignProperty(propDef);
			var propDataType = this.aras.getItemProperty(realPropDef, 'data_type');
			var propName = this.aras.getItemProperty(propDef, 'name');

			if ('item' != propDataType) {
				groupDefinition.push(this._generatePropertyDefinition(propName, propDataType));
			}
		}
	}

	groupDefinition.push('  </xs:choice>');
	groupDefinition.push('</xs:complexType>');

	this.schemaGlobalObjects.push(groupDefinition.join(''));

	return nameOfNotDefinition;
};

AmlValidator.prototype.generateItemPropertyDefinition = function AmlValidatorGenerateItemPropertyDefinition(propertyXPath, propName) {

	var itemPropertyArray = [];
	itemPropertyArray.push('<xs:element name="' + propName + '">');
	itemPropertyArray.push('  <xs:complexType>');
	itemPropertyArray.push('    <xs:choice minOccurs="0" maxOccurs="unbounded">');
	for (var currentXPath in this.validationInfoObject) {
		if (currentXPath.indexOf(propertyXPath) == -1) {
			continue;
		}

		var newItemXPath = '';
		var withKeyedName = false;

		if (currentXPath == propertyXPath) {
			var propDef = this.validationInfoObject[currentXPath];
			var realPropertyDef = this.aras.getRealPropertyForForeignProperty(propDef);
			var propertyDataSource = this.aras.getItemPropertyAttribute(realPropertyDef, 'data_source', 'name');
			var typeCriterion = '';
			if (propertyDataSource) {
				typeCriterion = '[@type=\'' + propertyDataSource + '\']';
			}

			newItemXPath = currentXPath + '/Item' + typeCriterion;
			if (!this.validationInfoObject[newItemXPath + '/keyed_name']) {
				withKeyedName = true;
			}
		} else {
			var currentXPathArray = currentXPath.split('/');
			var propertyXPathDeep = propertyXPath.split('/').length;

			var newItemXPathArray = [];
			for (var j = 0; j < propertyXPathDeep; j++) {
				newItemXPathArray.push(currentXPathArray[j]);
			}

			newItemXPath = newItemXPathArray.join('/');
			// Exclude situation when
			// currentXPath = "Item[@type="InBasket Task"]/container_type_id" and
			// propertyXPath = "Item[@type="InBasket Task"]/container"
			if (newItemXPath.length > 0 && newItemXPath != propertyXPath) {
				continue;
			}

			newItemXPath += '/' + currentXPathArray[propertyXPathDeep];

			withKeyedName = false;
			if (this.validationInfoObject[newItemXPath] && !this.validationInfoObject[newItemXPath + '/keyed_name']) {
				withKeyedName = true;
				this.aras.deletePropertyFromObject(this.validationInfoObject, newItemXPath);
			}
		}

		itemPropertyArray.push(this.generateItemDefinition(newItemXPath, false, withKeyedName));
	}
	itemPropertyArray.push('    </xs:choice>');
	itemPropertyArray.push('    <xs:attribute name="condition" type="' + this.types.item + '" use="optional"/>');
	itemPropertyArray.push('  </xs:complexType>');
	itemPropertyArray.push('</xs:element>');
	return itemPropertyArray.join('');
};

AmlValidator.prototype.generateInnerItemDefinition = function AmlValidatorGenerateInnerItemDefinition(parentItemXPath, parentItemDef, withKeyedName) {
	var transformedParentItemXPath = this._transformXPath(parentItemXPath);

	var orName = 'OR-' + transformedParentItemXPath;
	var orGroupName = 'OR-Group-' + transformedParentItemXPath;

	var notName = this.generateDefinitionForNotGroup(parentItemXPath, parentItemDef, withKeyedName);

	this.schemaGlobalObjects.push('<xs:complexType name="' + orName + '">');
	this.schemaGlobalObjects.push('  <xs:choice maxOccurs="unbounded">');
	this.schemaGlobalObjects.push('    <xs:group ref="' + orGroupName + '" maxOccurs="unbounded"/>');
	this.schemaGlobalObjects.push('  </xs:choice>');
	this.schemaGlobalObjects.push('</xs:complexType>');

	var orGroupDefinition = [];
	orGroupDefinition.push('<xs:group name="' + orGroupName + '">');
	orGroupDefinition.push('  <xs:choice>');
	orGroupDefinition.push('    <xs:element name="OR" type="' + orName + '"/>');
	orGroupDefinition.push('    <xs:element name="NOT" type="' + notName + '"/>');

	var parentItemXPathDeep = parentItemXPath.split('/').length;

	parentItemDef.push('      <xs:choice minOccurs="0" maxOccurs="unbounded">');

	if (withKeyedName) {
		parentItemDef.push('      <xs:element name="keyed_name" type="CONST-string"/>');
		orGroupDefinition.push('    <xs:element name="OR-keyed_name" type="CONST-OR-keyed_name"/>');
	}

	for (var currentXPath in this.validationInfoObject) {
		if (currentXPath.indexOf(parentItemXPath) == -1) {
			continue;
		}

		var propName;
		var currentXPathArray = currentXPath.split('/');
		var currentXPathDeep = currentXPathArray.length;
		if (currentXPathDeep == parentItemXPathDeep + 1) {
			var propDef = this.validationInfoObject[currentXPath];
			var realPropDef = this.aras.getRealPropertyForForeignProperty(propDef);
			var propDT = this.aras.getItemProperty(realPropDef, 'data_type');
			propName = this.aras.getItemProperty(propDef, 'name');

			if ('item' != propDT) {
				var orTypeName = 'OR-' + transformedParentItemXPath + propName;

				parentItemDef.push(this._generatePropertyDefinition(propName, propDT));
				orGroupDefinition.push('<xs:element name="OR-' + propName + '" type="' + orTypeName + '"/>');

				this.schemaGlobalObjects.push(this._generatePropertyOR(orTypeName, propName, propDT));
			} else {
				parentItemDef.push(this.generateItemPropertyDefinition(parentItemXPath + '/' + propName, propName));
			}
		} else {
			propName = currentXPathArray[parentItemXPathDeep];
			parentItemDef.push(this.generateItemPropertyDefinition(parentItemXPath + '/' + propName, propName));
		}

		this.aras.deletePropertyFromObject(this.validationInfoObject, currentXPath);
	}

	orGroupDefinition.push('  </xs:choice>');
	orGroupDefinition.push('</xs:group>');

	this.schemaGlobalObjects.push(orGroupDefinition.join(''));

	parentItemDef.push('        <xs:group ref="' + orGroupName + '"/>');
	parentItemDef.push('      </xs:choice>');
};

AmlValidator.prototype.generateConditionDefinition = function AmlValidatorGenerateConditionDefinition(conditionNum, allowedValuesArr) {
	var conditionDefinitions = [];
	conditionDefinitions.push('  <xs:simpleType name="CONST-Condition-' + conditionNum + '">');
	conditionDefinitions.push('    <xs:restriction base="xs:string">');

	for (var i = 0; i < allowedValuesArr.length; i++) {
		conditionDefinitions.push('      <xs:enumeration value="' + allowedValuesArr[i] + '"/>');
	}

	conditionDefinitions.push('    </xs:restriction>');
	conditionDefinitions.push('  </xs:simpleType>');
	return conditionDefinitions.join('');
};

AmlValidator.prototype.generateItemAttributesDefinition = function AmlValidatorGenerateItemAttributesDefinition(typeOfItem, itemDefinition, isRoot) {
	itemDefinition.push('      <xs:attribute name="action" type="action-attribute" use="required"/>');
	if (typeOfItem) {
		itemDefinition.push('      <xs:attribute name="type" use="required">');
		itemDefinition.push('        <xs:simpleType>');
		itemDefinition.push('          <xs:restriction base="xs:string">');
		itemDefinition.push('            <xs:enumeration value="' + typeOfItem + '"/>');
		itemDefinition.push('          </xs:restriction>');
		itemDefinition.push('        </xs:simpleType>');
		itemDefinition.push('      </xs:attribute>');
	}

	if (isRoot) {
		itemDefinition.push('      <xs:attribute name="typeId" use="optional">');
		itemDefinition.push('        <xs:simpleType>');
		itemDefinition.push('          <xs:restriction base="xs:string">');
		itemDefinition.push('            <xs:length value="32"/>');
		itemDefinition.push('          </xs:restriction>');
		itemDefinition.push('        </xs:simpleType>');
		itemDefinition.push('      </xs:attribute>');
		itemDefinition.push('      <xs:attribute name="page" type="integer-as-string" use="optional" />');
		itemDefinition.push('      <xs:attribute name="pagesize" type="integer-as-string" use="optional" />');
		itemDefinition.push('      <xs:attribute name="maxRecords" type="integer-as-string" use="optional" />');
		itemDefinition.push('      <xs:attribute name="returnMode" type="xs:string" use="optional" />');
		itemDefinition.push('      <xs:attribute name="select" type="xs:string" use="optional"/>');
		itemDefinition.push('      <xs:attribute name="queryType" type="xs:string" use="optional"/>');
		itemDefinition.push('      <xs:attribute name="queryDate" type="xs:string" use="optional"/>');

		if (this.aras.getVariable('SortPages') == 'true') {
			itemDefinition.push('      <xs:attribute name="order_by" type="xs:string" use="optional"/>');
		}
	}
};

AmlValidator.prototype.generateConditions = function AmlValidatorGenerateConditions() {
	var res = '';
	res += this.generateConditionDefinition(0, new Array('eq', 'ne'));
	res += this.generateConditionDefinition(1, new Array('is null', 'is not null'));
	res += this.generateConditionDefinition(2, new Array('eq', 'ne', 'is null', 'is not null'));
	res += this.generateConditionDefinition(3, new Array('eq', 'ne', 'like', 'not like', 'is null', 'is not null'));
	res += this.generateConditionDefinition(4, new Array('eq', 'ne', 'lt', 'gt', 'le', 'ge', 'is null', 'is not null'));
	res += this.generateConditionDefinition(5, new Array('eq', 'ne', 'lt', 'gt', 'le', 'ge', 'is null', 'is not null', 'between', 'not between'));

	return res;
};

AmlValidator.prototype.generateTypeDefinition = function AmlValidatorGenerateTypeDefinition(innovatorTypesArr, typeName, conditionType, baseTypeName) {
	this.types[typeName] = conditionType;
	if ('integer' == typeName && !baseTypeName) {
		baseTypeName = 'integer-or-empty-string';
		innovatorTypesArr.push('  <xs:simpleType name="' + baseTypeName + '">');
		innovatorTypesArr.push('    <xs:restriction base="xs:string">');
		innovatorTypesArr.push('      <xs:pattern value="([-+]?[0-9]+)?"/>');
		innovatorTypesArr.push('    </xs:restriction>');
		innovatorTypesArr.push('  </xs:simpleType>');
	}

	if (!baseTypeName) {
		baseTypeName = 'xs:string';
	}

	innovatorTypesArr.push('  <xs:complexType name="CONST-' + typeName + '">');
	innovatorTypesArr.push('    <xs:simpleContent>');
	innovatorTypesArr.push('      <xs:extension base="' + baseTypeName + '">');
	innovatorTypesArr.push('        <xs:attribute name="condition" type="' + conditionType + '"/>');
	innovatorTypesArr.push('      </xs:extension>');
	innovatorTypesArr.push('    </xs:simpleContent>');
	innovatorTypesArr.push('  </xs:complexType>');
};

AmlValidator.prototype.generateTypes = function AmlValidatorGenerateTypes() {
	var typesArray = [];
	this.generateTypeDefinition(typesArray, 'boolean', 'CONST-Condition-0', 'xs:boolean');
	this.generateTypeDefinition(typesArray, 'color', 'CONST-Condition-3');
	this.generateTypeDefinition(typesArray, 'color-list', 'CONST-Condition-2');
	this.generateTypeDefinition(typesArray, 'date', 'CONST-Condition-5');
	this.generateTypeDefinition(typesArray, 'decimal', 'CONST-Condition-4', 'xs:decimal');
	this.generateTypeDefinition(typesArray, 'federated', 'CONST-Condition-3');
	this.generateTypeDefinition(typesArray, 'filter-list', 'CONST-Condition-2');
	this.generateTypeDefinition(typesArray, 'float', 'CONST-Condition-4', 'xs:float');
	this.generateTypeDefinition(typesArray, 'formatted-text', 'CONST-Condition-3');
	this.generateTypeDefinition(typesArray, 'image', 'CONST-Condition-3');
	this.generateTypeDefinition(typesArray, 'integer', 'CONST-Condition-4');
	this.generateTypeDefinition(typesArray, 'item', 'CONST-Condition-3');
	this.generateTypeDefinition(typesArray, 'list', 'CONST-Condition-2');
	this.generateTypeDefinition(typesArray, 'md5', 'CONST-Condition-2');
	this.generateTypeDefinition(typesArray, 'ml_string', 'CONST-Condition-3');
	this.generateTypeDefinition(typesArray, 'mv_list', 'CONST-Condition-4');
	this.generateTypeDefinition(typesArray, 'sequence', 'CONST-Condition-4');
	this.generateTypeDefinition(typesArray, 'string', 'CONST-Condition-3');
	this.generateTypeDefinition(typesArray, 'text', 'CONST-Condition-3');
	this.generateTypeDefinition(typesArray, 'global_version', 'CONST-Condition-5', 'unsigned-big-integer-or-empty-string');
	this.generateTypeDefinition(typesArray, 'ubigint', 'CONST-Condition-5', 'unsigned-big-integer-or-empty-string');

	return typesArray.join('');
};

AmlValidator.prototype.generateSchema = function AmlValidatorGenerateSchema(validationInfoObject) {
	this.validationInfoObject = validationInfoObject;

	this.schemaGlobalObjects = [];
	this.schemaGlobalObjects.push('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>');
	this.schemaGlobalObjects.push('<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" elementFormDefault="qualified">');
	this.schemaGlobalObjects.push(this.generateTypes());
	this.schemaGlobalObjects.push(this.generateConditions());
	this.schemaGlobalObjects.push(this.generateItemDefinition(this.getRootItemXPath(), true, false));
	this.schemaGlobalObjects.push('  <xs:complexType name="CONST-OR-keyed_name">');
	this.schemaGlobalObjects.push('    <xs:choice maxOccurs="unbounded">');
	this.schemaGlobalObjects.push('      <xs:element name="keyed_name" type="CONST-string"/>');
	this.schemaGlobalObjects.push('      <xs:element name="OR-keyed_name" type="CONST-OR-keyed_name"/>');
	this.schemaGlobalObjects.push('    </xs:choice>');
	this.schemaGlobalObjects.push('  </xs:complexType>');
	this.schemaGlobalObjects.push('  <xs:simpleType name="integer-as-string">');
	this.schemaGlobalObjects.push('    <xs:restriction base="xs:string">');
	this.schemaGlobalObjects.push('      <xs:pattern value="|\\d*"/>');
	this.schemaGlobalObjects.push('    </xs:restriction>');
	this.schemaGlobalObjects.push('  </xs:simpleType>');
	this.schemaGlobalObjects.push('  <xs:simpleType name="unsigned-big-integer-or-empty-string">');
	this.schemaGlobalObjects.push('    <xs:restriction base="xs:string">');
	this.schemaGlobalObjects.push('      <xs:pattern value="([0-9]){0,20}"/>');
	this.schemaGlobalObjects.push('    </xs:restriction>');
	this.schemaGlobalObjects.push('  </xs:simpleType>');
	this.schemaGlobalObjects.push('  <xs:simpleType name="action-attribute">');
	this.schemaGlobalObjects.push('    <xs:restriction base="xs:string">');
	this.schemaGlobalObjects.push('      <xs:enumeration value="get"/>');
	this.schemaGlobalObjects.push('    </xs:restriction>');
	this.schemaGlobalObjects.push('  </xs:simpleType>');
	this.schemaGlobalObjects.push('</xs:schema>');

	return this.schemaGlobalObjects.join('');
};
/*@cc_on
@if (@register_classes == 1)
Type.registerNamespace("Aras");
Type.registerNamespace("Aras.Client");
Type.registerNamespace("Aras.Client.JS");

Aras.Client.JS.AmlValidator = AmlValidator;
Aras.Client.JS.AmlValidator.registerClass("Aras.Client.JS.AmlValidator");
@end
@*/

/** search_grid.js **/
// (c) Copyright by Aras Corporation, 2004-2013.
var currQryItem;
var currItemType = null;
var itemTypeID = '';
var itemTypeName = '';
var itemTypeLabel = '';
var visiblePropNds;
var userMethodColumnCfgs = {}; //to support OnSearchDialog grid event
var searchLocation = '';

var page = 1;
var pagemax = -1;
var itemmax = 0;
var pagesize = '';
var maxRecords = '';
var inputCol = -1;
var ps;
var inputRowId = 'input_row';

var xmlReadyFlag = false;
var promiseCountResult;

function initPage(isPopup) {
	var criteriaName;
	var criteriaValue;

	if (itemTypeID) {
		//itemTypeID has higher priority because of poly items
		criteriaName = 'id';
		criteriaValue = itemTypeID;
	} else if (itemTypeName) {
		criteriaName = 'name';
		criteriaValue = itemTypeName;
	} else {
		aras.AlertError(aras.getResource('', 'search.neither_input_item_type_name_nor_id_specified'));
		if (isPopup) {
			window.close();
		}
		return false;
	}

	var iomItemType = aras.getItemTypeForClient(criteriaValue, criteriaName);
	if (iomItemType.isError()) {
		if (isPopup) {
			window.close();
		}
		return false;
	}

	currItemType = iomItemType.node;
	itemTypeID = currItemType.getAttribute('id');
	itemTypeName = aras.getItemProperty(currItemType, 'name');
	itemTypeLabel = aras.getItemProperty(currItemType, 'label');
	if (!itemTypeLabel) {
		itemTypeLabel = itemTypeName;
	}

	currQryItem = aras.newQryItem(itemTypeName);

	visiblePropNds = [];

	visiblePropNds = aras.getvisiblePropsForItemType(currItemType);
	aras.uiInitItemsGridSetups(currItemType, visiblePropNds);

	setTimeout(function() {
		showStatus();
	}, 300);
}

function initToolbar() {
	if (!window.searchbar) {
		return;
	}

	const searchToolbar = searchbar.getActiveToolbar();
	if (!multiselect) {
		searchToolbar.getItem('select_all').disable();
	}

	if (aras.isPolymorphic(currItemType)) {
		let cb = searchToolbar.getItem('implementation_type');
		cb.removeAll();
		cb.Add(itemTypeID, itemTypeLabel);
		const morphae = aras.getMorphaeList(currItemType);
		for (let i = 0; i < morphae.length; i++) {
			const m = morphae[i];
			cb.Add(m.id, m.label);
		}
		cb = null;
		searchToolbar.showItem('implementation_type');
	} else {
		searchToolbar.hideItem('implementation_type');
	}
}

function initPaginationToolbar() {
	let pageSizeValue = aras.getPreferenceItemProperty('Core_ItemGridLayout', itemTypeID, 'page_size', null);
	let maxResultsValue = aras.getPreferenceItemProperty('Core_ItemGridLayout', itemTypeID, 'max_records', null);
	if (pageSizeValue === null) {
		pageSizeValue = aras.getItemProperty(currItemType, 'default_page_size');
	}
	if (maxResultsValue === null) {
		maxResultsValue = aras.getItemProperty(currItemType, 'maxrecords');
	}

	pagination.pageSize = pageSizeValue;
	pagination.maxResults = maxResultsValue;
}

function getPaginationButtonsState() {
	const isAppend = (aras.getPreferenceItemProperty('Core_GlobalLayout', null, 'core_append_items') === 'true');

	const prevButtonState = (!isAppend && page > 1);

	pagesize = currQryItem.getPageSize();
	maxRecords = currQryItem.getMaxRecords();
	const nodes = currQryItem.getResultDOM().selectNodes('/' + SoapConstants.EnvelopeBodyXPath + '/Result/Item');
	let itemsQuantity;
	if (maxRecords && pagesize) {
		itemsQuantity = pagesize * (page - 1) + nodes.length;
		if (isAppend) {
			itemsQuantity = nodes.length;
		}
	}
	if (itemmax) {
		pagemax = itemmax / pagination.pageSize;
	}
	const nextButtonState = !(pagemax === page || itemsQuantity == maxRecords || nodes.length < pagesize) && nodes.length !== 0 && pagesize !== '-1';
	const moreButtonState = !(page === 1 && nodes.length === 0);

	return {
		prevButtonState: prevButtonState,
		nextButtonState: nextButtonState,
		moreButtonState: moreButtonState
	};
}

function updatePagination() {
	const buttonsState = getPaginationButtonsState();
	pagination.updateControlsStateByDefault();

	pagination.setItemEnabled('pagination_prev_button', buttonsState.prevButtonState);
	pagination.setItemEnabled('pagination_next_button', buttonsState.nextButtonState);
	pagination.setItemEnabled('pagination_more_button', buttonsState.moreButtonState);
	pagination.setItemEnabled('pagination_status_node', buttonsState.moreButtonState);

	return pagination.render();
}

function doSearch() {
	if (searchContainer) {
		searchContainer.runSearch();
	} else {
		setTimeout(function() {
			doSearch();
		}, 50);
	}
}

function doSelectAll() {
	statusId = aras.showStatusMessage('status', aras.getResource('', 'search.selecting_all'), '../images/Progress.gif');

	grid.selectAll();
	var ids = grid.GetSelectedItemIDs();
	if (ids.length > 0 && onSelectItem) {
		onSelectItem(ids[0]);
	}

	aras.clearStatusMessage(statusId);
}

function onSelectItem() {
}

function setupPageNumber(anyItem) {
	if (!anyItem) {
		anyItem = currQryItem.getResponseDOM().selectSingleNode('//Item');
	}
	page = 1;
	pagemax = -1;
	var itemsWithNoAccesCount = currQryItem.getResponse().getMessageValue('items_with_no_access_count');
	if (itemsWithNoAccesCount) {
		currentSearchMode.setCacheItem('itemsWithNoAccessCount', parseInt(itemsWithNoAccesCount));
	}
	if (anyItem) {
		var pagesize = currQryItem.getPageSize();
		if (pagesize == '-1') {
			pagemax = 1;
			itemmax = currQryItem.getResultDOM().selectNodes('/' + SoapConstants.EnvelopeBodyXPath + '/Result/Item').length;
		} else {
			pagemax = anyItem.getAttribute('pagemax');
			itemmax = anyItem.getAttribute('itemmax');
		}
		page = anyItem.getAttribute('page');
		var cacheValue = function(value, cacheKey) {
			if (value && !currentSearchMode.getCacheItem(cacheKey)) {
				currentSearchMode.setCacheItem(cacheKey, value);
			} else {
				value = currentSearchMode.getCacheItem(cacheKey);
			}
			return value;
		};
		currentSearchMode.setCacheItem('criteriesHash', ArasModules.utils.hashFromString(currQryItem.getCriteriesString()));
		itemmax = cacheValue(itemmax, 'itemmax');
		pagemax = cacheValue(pagemax, 'pagemax');
		if (!page) {
			page = 1;
		}
		if (!pagemax) {
			pagemax = -1;
		}
	}
}

function updateToolStatusBar(totalItems) {
	pagination.updateControlsState();
	showStatus();
	return Promise.resolve(totalItems);
}

function setupGrid(isGridInitXml, doNotRenderRows) {
	var isRelationshipsGrid = (searchLocation === 'Relationships Grid');
	var resDom = currQryItem.getResultDOM();
	if (!resDom) {
		return;
	}

	var itTypeId = '';
	if (isRelationshipsGrid) {
		itTypeId = aras.getRelationshipTypeId(window['RelType_Nm']);
		syncWithClient(resDom);
	} else {
		itTypeId = aras.getItemTypeId(itemTypeName);
		currQryItem.syncWithClient();
	}

	aras.uiPrepareDOM4XSLT(resDom, itTypeId, (isRelationshipsGrid ? 'RT_' : 'IT_'));

	var gridXml = '';
	var params = aras.newObject();
	params['only_rows'] = !isGridInitXml;
	if (!isRelationshipsGrid) {
		gridXml = aras.uiGenerateItemsGridXML(resDom, visiblePropNds, itTypeId, params);
	} else {
		params['enable_links'] = !isEditMode;
		params.enableFileLinks = true;
		params.bgInvert = true;
		if (window['RelatedItemType_ID']) {
			params[window['RelatedItemType_ID']] = '';
		}

		var tableNd = resDom.selectSingleNode(aras.XPathResult('/table'));
		tableNd.setAttribute('editable', (isEditMode ? 'true' : 'false'));

		gridXml = aras.uiGenerateRelationshipsGridXML(resDom, DescByVisibleProps, RelatedVisibleProps, window['DescByItemType_ID'], params, true);
	}

	if (isGridInitXml) {
		grid['InitXML_Experimental'](gridXml, doNotRenderRows);

		if (window.previewPane) {
			const userPreviewMode = aras.getPreferenceItemProperty('Core_ItemGridLayout', itemTypeID, 'preview_state', 'Off');
			previewPane.setType(userPreviewMode);
		}
	} else {
		if (grid.getRowCount() === 0) {
			grid.addXMLRows(gridXml);
		} else {
			grid['InitXMLRows_Experimental'](gridXml);
		}
	}

	xmlReadyFlag = true;
}

function createEmptyResultDom() {
	var resDom = aras.createXMLDocument();
	resDom.loadXML(SoapConstants.EnvelopeBodyStart + '<Result/>' + SoapConstants.EnvelopeBodyEnd);
	return resDom;
}

onbeforeunload = function onbeforeunloadHandler() {
	window.isOnBeforeUnload = true;

	saveSetups();

	window.isOnBeforeUnload = false;
};

function saveSetups() {
	if (!xmlReadyFlag) {
		return;
	}

	if (searchContainer) {
		searchContainer.onEndSearchContainer();
	}

	const varsHash = {};
	const isRelationshipsGrid = (searchLocation === 'Relationships Grid');
	const currToolBar = (isRelationshipsGrid ? document.toolbar : currentSearchMode.searchToolbar);

	const maxResults = pagination.maxResults;
	ps = pagination.pageSize;
	if (ps || ps === 0) {
		varsHash['page_size'] = ps || '';
	}
	if (maxResults || maxResults === 0) {
		varsHash['max_records'] = maxResults || '';
	}

	if (currToolBar && isMainGrid && isVersionableIT) {
		const queryType = currToolBar.data.get('searchview.commandbar.default.querytype').value;
		let queryDate = currToolBar.data.get('searchview.commandbar.default.querydate').value;
		queryDate = aras.convertToNeutral(queryDate, 'date', GetDatePattern(queryType));
		varsHash['query_type'] = queryType;
		if (queryType !== 'Current') {
			aras.setVariable(window['varName_queryDate'], queryDate);
		}
	}

	varsHash['col_widths'] = window.grid.GetColWidths();
	varsHash['col_order'] = window.grid.getLogicalColumnOrder();

	let tmpId;
	let tmpTypeNm;
	if (isRelationshipsGrid) {
		tmpId = aras.getRelationshipTypeId(window['RelType_Nm']);
		tmpTypeNm = 'Core_RelGridLayout';
	} else {
		if (window.previewPane) {
			varsHash['preview_state'] = window.previewPane.getType();
		}

		tmpId = aras.getItemTypeId(itemTypeName);
		tmpTypeNm = 'Core_ItemGridLayout';
		if (window.grid._grid && window.grid._grid.view.defaultSettings.freezableColumns) {
			varsHash['frozen_columns'] = String(window.grid._grid.settings.frozenColumns);
		}
	}
	aras.setPreferenceItemProperties(tmpTypeNm, tmpId, varsHash);
}

function onLink(itemTypeName, itemID) {
	aras.uiShowItem(itemTypeName, itemID);
}

function startCellEditCommon(rowId, field) {
	if (inputRowId == rowId) {
		setupFilteredListIfNeed(rowId, field);
	}
}

function applyCellEditCommon(rowId, field) {
	if (inputRowId == rowId && searchReady) {
		const prevSearchAml = currentSearchMode.getAml();

		const grid = this;
		const columnIndex = this.GetColumnIndex(field);
		const inputCell = this['grid_Experimental'].inputRowCollections[field] || {get: function() {},
			focus: function() {
				grid._grid.settings.focusedCell = {rowId: 'searchRow', headId: field};
				grid._oldSearchHeadId = field;
			}
		};
		const criteria = this.inputRow.get(field, 'value');
		const useWildcards = (aras.getPreferenceItemProperty('Core_GlobalLayout', null, 'core_use_wildcards') == 'true');
		const condition = (useWildcards ? 'like' : 'eq');

		const propDef = searchContainer.getPropertyDefinitionByColumnIndex(columnIndex);
		const propXpath = searchContainer.getPropertyXPathByColumnIndex(columnIndex);

		if (currentSearchMode.setSearchCriteria(propDef, propXpath, criteria, condition)) {
			inputCell._lastValueReported = inputCell.get('value');
		} else {
			inputCell._lastValueReported = '';
			if (aras.confirm(aras.getResource('', 'search.invalid_criteria'))) {
				inputCell.focus();
			} else {
				currentSearchMode.removeSearchCriteria(propXpath);
				this.inputRow.set(field, 'value', '');
			}
		}

		if (prevSearchAml !== currentSearchMode.getAml()) {
			currentSearchMode.setPageNumber(1);
			if (window.pagination) {
				pagination.resetControlsState();
			}
		}
	}

}

function setupFilteredListIfNeed(rowID, field) {
	if (inputRowId !== rowID) {
		return;
	}
	var col = window.grid['columns_Experimental'].get(field, 'index');

	var propNd = visiblePropNds[col - 1];
	if (!propNd || !propNd.xml) {
		return;
	}

	var propName = aras.getItemProperty(propNd, 'name');
	var propDataType = aras.getItemProperty(propNd, 'data_type');
	if (propDataType != 'filter list') {
		return;
	}

	var propPatternName = aras.getItemProperty(propNd, 'pattern');
	if (!propPatternName) {
		return;
	}

	var patternColIndexArr = [];
	for (var i = 0; j < visiblePropNds.length; i++) {
		var curPropName = aras.getItemProperty(visiblePropNds[i], 'name');
		if (curPropName == propPatternName) {
			patternColIndexArr.push(i);
		}
	}

	for (var j = 0; j < patternColIndexArr.length; j++) {
		var filterValue = window.grid.inputRow.get(patternColIndexArr[j] + 1, 'value') || '';
		var resObj = aras.uiGetFilteredObject4Grid(itemTypeID, propName, filterValue);
		if (resObj.hasError) {
			return;
		}

		window.grid.inputRow.set(col, 'comboList', resObj.labels, resObj.values);
	}
}

function removeFilterListValueIfNeed(rowID, field) {
	if (inputRowId !== rowID) {
		return;
	}
	var col = grid['columns_Experimental'].get(field, 'index');

	var propNd = visiblePropNds[col - 1];
	if (!propNd || !propNd.xml) {
		return;
	}

	var propName = aras.getItemProperty(propNd, 'name');
	var propDataType = aras.getItemProperty(propNd, 'data_type');
	if (propDataType != 'filter list') {
		return;
	}

	var filteredColIndexArr = [];
	var j;
	for (j = 0; j < visiblePropNds.length; j++) {
		var curPropPattern = aras.getItemProperty(visiblePropNds[j], 'pattern');
		if (curPropPattern == propName) {
			filteredColIndexArr.push(j);
		}
	}

	for (j = 0; j < filteredColIndexArr.length; j++) {
		grid.inputRow.set(filteredColIndexArr[j] + 1, 'value', '');
	}
}

function getAndUpdatePageSizeAndMaxRecords() {
	currentSearchMode.removeCacheItem('itemmax');
	currentSearchMode.removeCacheItem('pagemax');
	currentSearchMode.removeCacheItem('criteriesHash');
	itemmax = currentSearchMode.getCacheItem('itemmax');
	pagemax = currentSearchMode.getCacheItem('pagemax');
	const pagesize = currQryItem.getPageSize();
	const maxRecords = currQryItem.getMaxRecords();
	if (!itemmax || !pagemax) {
		showStatus();
		const item = aras.newIOMItem(currQryItem.itemTypeName, 'get');
		item.setAttribute('returnMode', 'countOnly');
		item.setAttribute('select', 'id');
		item.setAttribute('pagesize', pagesize);
		if (maxRecords) {
			item.setAttribute('maxRecords',maxRecords);
		}
		const criteries = currQryItem.dom.selectNodes('/Item/*');
		for (let i = 0; i < criteries.length; i++) {
			item.dom.firstChild.appendChild(criteries[i].cloneNode(true));
		}
		promiseCountResult = Promise.resolve(aras.soapSend('ApplyItem', item.node.xml).results);
		return promiseCountResult
			.then(parseAnswerGetCount)
			.then(updateToolStatusBar);
	}
	return Promise.resolve(null);
}

function parseAnswerGetCount(res) {
	promiseCountResult = null;
	if (aras.hasFault(res)) {
		aras.AlertError(res);
		updateToolStatusBar();
		return;
	}
	res = aras.getMessageNode(res);
	itemmax = res.selectSingleNode('event[@name="itemmax"]').getAttribute('value');
	pagemax = res.selectSingleNode('event[@name="pagemax"]').getAttribute('value');
	currentSearchMode.setCacheItem('criteriesHash', ArasModules.utils.hashFromString(currQryItem.getCriteriesString()));
	currentSearchMode.setCacheItem('itemmax', itemmax);
	currentSearchMode.setCacheItem('pagemax', pagemax);
	currentSearchMode.setCacheItem('itemsWithNoAccessCount', parseInt(res.selectSingleNode('event[@name="items_with_no_access_count"]').getAttribute('value')));
	return Promise.resolve(itemmax);
}

function showStatus() {
	if (window.isMainGrid && pagemax === -1) {
		pagination.showMoreButton();

		return;
	}

	const nodes = currQryItem.getResultDOM().selectNodes('/' + SoapConstants.EnvelopeBodyXPath + '/Result/Item');
	if (itemmax) {
		pagination.showTotalResults(nodes.length !== 0 ? itemmax : 0);
	} else {
		pagination.showMoreButton();
	}
}

/** SearchGridObject.js **/
// (c) Copyright by Aras Corporation, 2006-2007.

/*
This file contains logic common for all search grids (grid + searchbar)
*/

var grid = null;
var isMainGrid = false; //this flag is used because behavior is not completely identical
var soapController = null; //controller to manage async soap requests
var statusId; //variable to store message id during async search
var prevQryItem; //previos search results
//------------------------

function setupSearchButtonsStates(searchIsInProgress) {
	/*
	setups states of search buttons:
	stop_search, search
	----
	searchIsInProgress - boolean flag indicating if search is in progress
	*/

	if (!searchContainer || !searchContainer.getToolbar()) {
		return;
	}

	const activeToolbar = searchContainer.getToolbar().getActiveToolbar();
	let toolbarItem = activeToolbar.getItem('stop_search');
	if (toolbarItem) {
		toolbarItem.setEnabled(searchIsInProgress);
	}

	 toolbarItem = activeToolbar.getItem('search');
	if (toolbarItem) {
		toolbarItem.setEnabled(!searchIsInProgress);
	}
}

function whenGetResponse(result) {
	soapController = null;

	var faultCode = result.getFaultCode();
	setupSearchButtonsStates(false);
	clearSearchInProgressMessage();

	notifyCuiLayout('SearchStateChange');

	if (parseInt(faultCode) !== 0) {
		aras.AlertError(result);
		return;
	} else if (faultCode === '0' && currQryItem.getPage() !== '1' && ArasModules.utils.hashFromString(currQryItem.getCriteriesString()) === currentSearchMode.getCacheItem('criteriesHash')) {
		var currentPage = Math.max(currentSearchMode.getPageNumber() - 1, 1);
		currentSearchMode.setPageNumber(currentPage);
		pagemax = currentPage.toString();
		updateToolStatusBar();
		setupGrid(false);
		return;
	}


	currQryItem.setResponse(result);

	setupPageNumber();

	setupGrid(false);
	updateToolStatusBar();

	var nodes = currQryItem.getResultDOM().selectNodes('/' + SoapConstants.EnvelopeBodyXPath + '/Result/Item');
	if (nodes.length === 0 && searchContainer._isNoCountModeForCurrentItemType()) {
		getAndUpdatePageSizeAndMaxRecords();
	}
}

function notifyCuiLayout(eventType) {
	if (window.layout) {
		window.layout.observer.notify(eventType);
	}
}

function clearSearchInProgressMessage() {
	if (!statusId) {
		return;
	}

	if (isMainGrid) {
		aras.clearStatusMessage(statusId);
	} else if (document.frames && document.frames.statusbar) {
		document.frames.statusbar.clearStatus(statusId);
	}

	statusId = '';
}

function doSearch_internal() {
	stopSearch(false);
	setupSearchButtonsStates(true);

	const statusbar = document.frames ? document.frames.statusbar : null;
	if (!isMainGrid && statusbar) {
		statusId = statusbar.contentWindow.setStatus('status', aras.getResource('', 'common.searching_msg'), '../images/Progress.gif');
	}
	
	if (promiseCountResult) {
		promiseCountResult.abort();
		promiseCountResult = null;
	}
	
	soapController = new SoapController(whenGetResponse);
	currQryItem.execute(undefined, soapController);

	notifyCuiLayout('SearchStateChange');
}

onunload = function onunload_handler() {
	stopSearch(false);
};

function stopSearch(refresh) {
	if (refresh === undefined) {
		refresh = true;
	}
	
	if (soapController && soapController.stop) {
		soapController.stop();
		setupSearchButtonsStates(false);
		soapController = null;
	} else {
		return;
	}
	
	clearSearchInProgressMessage();

	if (refresh && prevQryItem) {
		currQryItem.dom.loadXML(prevQryItem);
		currQryItem.item = currQryItem.dom.documentElement;
		if (!isMainGrid) {
			page = currQryItem.getPage();
		}

		setupGrid(false);
		if (isMainGrid) {
			updateToolStatusBar();
		}
	}

	if (!isMainGrid && refresh) {
		showStatus();
	}

	notifyCuiLayout('SearchStateChange');
}

function InputHelperDialogResultHandler(col, val) {
	if (val || '' === val) {
		grid.inputRow.set(col, 'value', val);
		currQryItem.setPage(1);
		if (grid._grid) {
			const indexHead = grid._grid.settings.indexHead;
			grid._grid.dom.dispatchEvent(new CustomEvent('focusCell', {
				detail: {
					indexRow: 'searchRow',
					indexHead: indexHead.indexOf(grid.getColumnName(col))
				}
			}));
		}
	}
}

function showInputHelperDialog(rowId, col) {
	var prop = null;
	if (searchContainer && searchContainer.getPropertyDefinitionByColumnIndex) {
		prop = searchContainer.getPropertyDefinitionByColumnIndex(col);
	} else {
		var colName = grid.getColumnName(col);
		var propName = colName.substr(0, colName.length - 2);

		for (var i = 0; i < visiblePropNds.length; i++) {
			prop = visiblePropNds[i];
			if (aras.getItemProperty(prop, 'name') === propName) {
				break;
			}
		}
	}

	var aWindow = TopWindowHelper.getMostTopWindowWithAras(window);
	aWindow = aWindow.main || aWindow;
	var propDT = aras.getItemProperty(prop, 'data_type');
	var propName = aras.getItemProperty(prop, 'name');
	var val = null;
	var inputCell = grid.cells('input_row', col);
	var params;
	if (propDT === 'date') {
		var format = null;

		if (currentSearchMode && currentSearchMode.name === 'Simple') {
			format = aras.getDotNetDatePattern('short_date');
		} else {
			format = aras.getItemProperty(prop, 'pattern');
			format = aras.getDotNetDatePattern(format);
		}

		params = {
			format: format,
			aras: aras,
			type: 'Date'
		};

		var wndRect = aras.uiGetElementCoordinates(inputCell.cellNod_Experimental);
		var dateDialog = aWindow.ArasModules.Dialog.show('iframe', params);
		dateDialog.move(wndRect.left - wndRect.screenLeft, wndRect.top - wndRect.screenTop);
		dateDialog.promise.then(
			function(newDate) {
				var val;
				if (newDate) {
					val = aras.convertToNeutral(newDate, 'date', format);
				} else if (newDate === '') {
					val = '';
				}
				InputHelperDialogResultHandler(col, val);
				inputCell.cellNod_Experimental.querySelector('input').focus();
			}
		);

	} else if (propDT === 'image') {
		params = {
			aras: aras,
			image: grid.inputRow.get(col, 'value'),
			type: 'ImageBrowser'
		};
		aWindow.ArasModules.Dialog.show('iframe', params).promise.then(
			function(res) {
				val = 'set_nothing' === res ? '' : res;
				InputHelperDialogResultHandler(col, val);
			}
		);

	} else if (propDT === 'text') {
		params = {
			isEditMode: true,
			content: grid.inputRow.get(col, 'value'),
			aras: aras,
			type: 'Text'
		};
		aWindow.ArasModules.Dialog.show('iframe', params).promise.then(function(val) {
			InputHelperDialogResultHandler(col, val);
		}
		);
	} else if (propDT === 'formatted text') {
		params = {
			aras: aras,
			sHTML: grid.inputRow.get(col, 'value'),
			title: aras.getResource('', 'htmleditor.inn_formatted_text_editor'),
			type: 'HTMLEditorDialog'
		};
		aWindow.ArasModules.Dialog.show('iframe', params).promise.then(function(val) {
			InputHelperDialogResultHandler(col, val);
		}
		);

	} else if (propDT === 'color') {
		var oldColor = grid.inputRow.get(col, 'value');
		params = {
			oldColor: oldColor,
			aras: aras,
			type: 'Color'
		};
		aWindow.ArasModules.Dialog.show('iframe', params).promise.then(
			function(val) {
				InputHelperDialogResultHandler(col, val);
			}
		);
	} else if (propDT === 'item') {
		var propDS = aras.getItemProperty(prop, 'data_source');
		if (!propDS) {
			return;
		}

		var itName = aras.getItemTypeName(propDS);
		if (!itName) {
			return;
		}

		params = {
			aras: aWindow.aras,
			itemtypeName: itName,
			type: 'SearchDialog'
		};

		if (isMainGrid) {
			params.newWindowSizeHandler = function(popupDialog, params) {
				var mainWindow = aras.getMainWindow();
				aras.browserHelper.resizeWindowTo(mainWindow, params.newWidth, params.newHeight);
				params.cancelCallbacks.push(function() {
					aras.browserHelper.resizeWindowTo(mainWindow, params.oldWidth, params.oldHeight);
				});
			};
		}

		aWindow.ArasModules.MaximazableDialog.show('iframe', params).promise.then(
			function(res) {
				var val = res ? res.keyed_name : null;
				InputHelperDialogResultHandler(col, val);
			}
		);
	} else if (propDT === 'string' && propName === 'classification') {
		const classStructure = aras.getItemProperty(grid._itemType, 'class_structure');

		params = {
			title: aras.getItemProperty(prop, 'label'),
			isEditMode: true,
			aras: aWindow.aras,
			class_structure: classStructure,
			dialogType: 'classification',
			itemTypeName: aras.getItemProperty(grid._itemType, 'name'),
			selectLeafOnly: true,
			isRootClassSelectForbidden: true,
			dialogWidth: 600,
			dialogHeight: 700,
			resizable: true,
			content: 'ClassStructureDialog.html',
			expandClassPath: grid.inputRow.get(col, 'value')
		};

		aWindow.ArasModules.Dialog.show('iframe', params).promise.then(function(val) {
			InputHelperDialogResultHandler(col, val);
		});
	} else {
		aras.AlertError(aras.getResource('', 'search_grid_object.lookup_not_available', propDT));
	}
}

function saveEditedData() {
	grid.turnEditOff();
}

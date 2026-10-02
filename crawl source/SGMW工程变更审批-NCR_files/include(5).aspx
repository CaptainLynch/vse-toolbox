
/** ..\Modules\aras.innovator.CUI\Scripts\Classes\Utils.js **/
var CuiUtils = (function() {
	function Utils() {
		// Instance of ArrayListComparer should be created from main winodow because IOM is not included to Tear-off
		var mainWnd = aras.getMainWindow();
		this.arrayListComparer = new mainWnd.Aras.IOME.ArrayListComparer();
	}

	Utils.prototype.getDefaultContextItem = function() {
		return {itemType: window.itemType, itemID: window.itemID, item: window.item};
	};

	Utils.prototype.evalCommandBarItemMethod = function(methodId, contextItem, dontConvertParams, contextParams) {
		// todo: not sure that dontConvertParams is necessary
		if (!methodId) {
			throw 'methodId undefined';
		}
		var inArgs = dontConvertParams ? contextItem : this.createClientMethodParams(contextItem);
		if (contextParams) {
			inArgs.contextParams = contextParams;
		}
		return aras.evalMethod(methodId, '', inArgs);
	};

	Utils.prototype.createClientMethodParams = function(contextItem) {
		var params = Object.assign({}, contextItem); // copy contextParams to params
		if (contextItem.itemID) {
			params.itemId = contextItem.itemID;
		}
		if (contextItem.itemType) {
			params.itemTypeId = contextItem.itemType.getAttribute('id');
		}
		return params;
	};

	Utils.prototype.noItems = function(items) {
		return (!items || items.length < 1) ? true : false;
	};

	Utils.prototype.format = function() {
		var args = arguments;
		return args[0].replace(/{(\d+)}/g, function(match, number) {
			var num = parseInt(number) + 1;
			return typeof args[num] !== 'undefined' ? args[num] : '';
		});
	};

	Utils.prototype.getCommandBarItemAdditionalData = function(item, initHandlerResult) {
		var initData = item.selectSingleNode('additional_data');
		initData = initData ? initData.text : '';
		return this._getCommandBarItemAdditionalData(initData, initHandlerResult);
	};

	Utils.prototype._getCommandBarItemAdditionalData = function(initData, initHandlerResult) {
		if (initData) {
			initData = JSON.parse(initData);
		}

		if (initData) {
			if (initHandlerResult) {
				initData = Object.assign(initData, initHandlerResult);
			}
		} else {
			initData = initHandlerResult;
		}
		return initData;
	};

	Utils.prototype.applyAdditionalData = function(widget, data, noDataProps) {
		if (data) {
			var standardAdditionalDataProps = ['cui_style', 'cui_class', 'cui_visible', 'cui_base_class'];
			var domNode = widget.domNode || widget['_item_Experimental'].domNode;
			if (data['cui_style']) {
				domNode.setAttribute('style', domNode.getAttribute('style') + '; ' + data['cui_style']);
			}

			var classes = data['cui_class'];
			if (classes) {
				classes.split(' ').forEach(function(className) {
					if (!className.match(/^\s*$/)) {
						domNode.classList.add(className);
					}
				});
			}

			if (!noDataProps) {
				for (var prop in data) {
					if (data.hasOwnProperty(prop) && standardAdditionalDataProps.indexOf(prop) < 0) {
						widget.set(prop, data[prop]);
					}
				}
			}
		}
		return data;
	};

	Utils.prototype.getHandlerName = function(item, additionalData, handlerName) {
		return aras.getItemPropertyAttribute(item, handlerName, 'keyed_name') || (additionalData ? additionalData[handlerName] : null);
	};

	Utils.prototype.getOnInitHandlerName = function(item) {
		return this.getHandlerName(item, null, 'on_init_handler');
	};

	Utils.prototype.getOnClickHandler = function(item) {
		var methodId = this.getHandlerName(item, null, 'on_click_handler');
		var self = this;
		var evalOnClickHandler = function evalOnClickHandler(methodParams) {
			self.evalCommandBarItemMethod(methodId, methodParams);
		}.bind(this);

		return methodId ? evalOnClickHandler : null;
	};

	Utils.prototype.prepareInitHandlers = function(items) {
		var initHandlers = {};
		var currentItem;
		var methodId;
		for (var i = 0; i < items.length ; i++) {
			currentItem = items[i];
			var id = currentItem.getAttribute('id');
			methodId = currentItem.selectSingleNode('on_init_handler');
			methodId = methodId ? methodId.text : '';
			if (methodId) {
				var methodNd = aras.MetadataCache.GetClientMethodNd(methodId, 'id');
				if (methodNd) {
					/* jshint ignore:start */
					initHandlers[id] = new Function('control, inArgs', methodNd.selectSingleNode('method_code').text);
					/* jshint ignore:end */
				}
			}
		}
		return initHandlers;
	};

	Utils.prototype._mapExtraControlPropsToXml = function(props) {
		//'if (!props)' is kept for backward compatibility
		if (!props) {
			return '';
		}

		var extras = ' ';
		var propsKeys = Object.keys(props);
		for (var i = 0; i < propsKeys.length; i++) {
			var propValue = props[propsKeys[i]];
			if (propValue !== undefined) {
				extras += this.format('{0}="{1}" ', propsKeys[i], this._escapeXMLAttribute(propValue));
			}
		}

		return extras.trim();
	};

	Utils.prototype._escapeXMLAttribute = function(val) {
		return val.replace ? aras.escapeXMLAttribute(val) : val;
	};

	Utils.prototype.getHashCode = function(str) {
		var hash = 0;
		if (typeof str !== 'string' || str.length === 0) {
			return hash;
		}
		hash = this.arrayListComparer.getHashCode([str]);
		// In original implementation method return 'hash'. In that case 'hash' can be negative.
		// Return result is changed to '(hash >>> 0)'. It's allows to avoid negative results.
		return (hash >>> 0);
	};

	Utils.prototype.getParentMenuId = function(item) {
		const parenMenuNode = item && item.selectSingleNode('parent_menu');
		return parenMenuNode && parenMenuNode.text;
	};

	return Utils;
})();

/** ..\Modules\aras.innovator.CUI\Scripts\Classes\CuiTooltip.js **/
var CuiTooltip = (function() {

	function CuiTooltip() {
	}

	/**
	* parse tooltipTemplate (e.g. 'File ${File:@type} ${SecureMessageMarkup:markup_data(//page)}
	* from ${ItemType:label} ${Item:keyed_name}') and replace special properties.

	* @param {string} tooltipTemplate - can be whether template or just plain text.
	*/
	CuiTooltip.prototype._getTooltipFromTooltipTemplate = function getTooltipFromTooltipTemplate(tooltipTemplate) {
		var re = /\${[\w]+:@?[\w_]+}/g;
		var matches = tooltipTemplate.match(re);
		if (!matches) {
			return tooltipTemplate;
		}

		var topWnd = aras.getMostTopWindowWithAras();
		for (var i = 0; i < matches.length; i++) {
			var currentMatch = matches[i].replace(/[{}$]/g, '').split(':');
			var itemTypeName = currentMatch[0];
			var propertyName = currentMatch[1];

			var item;
			switch (itemTypeName) {
				case 'ItemType':
					item = topWnd.itemType;
					break;
				case 'Item':
					if (topWnd.item && topWnd.item.xml) {
						item = topWnd.item;
						if (aras.isNew(item)) { //set static tooltip instead of template when item is new
							return null;
						}
					}
					break;
			}

			var replacement;
			if (item) {
				if (propertyName.charAt(0) === '@') { //it's attribute
					replacement = item.getAttribute(propertyName.replace('@', '')) || ''; //set empty string if attribute of item does not exist
				} else {
					var propertyNode = item.selectSingleNode(propertyName);
					replacement = propertyNode === null ? '' : propertyNode.text; //set empty string if property of item does not exist or we haven't access to it
				}
			} else {
				replacement = aras.getResource(undefined, 'cui.tooltip_template_unavailable'); //set '[unavailable]' if user tries to get property of unsupported itemType
			}

			tooltipTemplate = tooltipTemplate.replace(matches[i], replacement);
		}
		return tooltipTemplate;
	};

	/**
	* Adds dojo's tooltip to button (widget).

	* @param {widgetId} id of button-widget to which a tooltip will be added.
	* @param {tooltipData} additionalData with properties for a tooltip.
	*/
	CuiTooltip.prototype.setTooltip = function(widgetId, tooltipData) {
		var tooltipWidget = dijit.byId(widgetId + '_tooltip');
		if (tooltipWidget) {//remove tooltip for widget if it exsists before create new
			tooltipWidget.destroy();
		}

		dijit.byId(widgetId).set('title', '');//disable standard tooltip
		var self = this;
		require(['dijit/Tooltip'], function(Tooltip) {
			new Tooltip({
				id: widgetId + '_tooltip',
				connectId: [widgetId],
				getContent: function() {
					var tooltipTemplate = this.tooltipData.template;
					if (tooltipTemplate !== undefined && tooltipTemplate !== null) {
						this.label = self._getTooltipFromTooltipTemplate(tooltipTemplate);
						if (this.label === null) {
							this.label = this.tooltipData.label;
						}
					} else {
						this.label = this.tooltipData.label;
					}

					return this.label;
				},
				tooltipData: tooltipData
			});
		}.bind(this));
	};

	CuiTooltip.prototype.makeOnClickHandlerForCommandBarMenu = function(tooltipWidget) {
		return function() {
			tooltipWidget.close();
		};
	};

	CuiTooltip.prototype.makeOnShowHandlerForCommandBarMenuTooltip = function(widget, tooltipWidget) {
		return function() {
			if (widget.dropDown.activated) {
				tooltipWidget.close();
			}
		};
	};

	return CuiTooltip;
})();

/** ..\Modules\aras.innovator.CUI\Scripts\Classes\CuiSidebar.js **/
var CuiSidebar = (function() {
	var mouse;
	var on;
	var dijit;
	var RadioButtonMenuItem;
	let DropDownMenu;
	require(['dojo/mouse', 'dojo/on', 'dijit/dijit', 'Controls/RadioButtonMenuItem', 'dijit/DropDownMenu', 'dijit/form/Button', 'dijit/form/DropDownButton'],
		function(_mouse, _on, _dijit, _RadioButtonMenuItem, _DropDownMenu) {
			mouse = _mouse;
			on = _on;
			dijit = _dijit;
			RadioButtonMenuItem = _RadioButtonMenuItem;
			DropDownMenu = _DropDownMenu;
		});

	function CuiSidebar() {
		//'private' object must be created at ConfigurableUI module.
		//If CuiSidebar module is used separately from ConfigurableUI module, 'private' object should be created in CuiSidebar constructor
		if (!this.private) {
			var self = this;
			this.private = {
				declare: function(fieldName, func) {
					var boundFunc = func.bind(self);
					this[fieldName] = boundFunc;
				}
			};
		}

		this.private.declare('loadSidebarImplementation', function(contextParams, async) {
			///<summary>Top-level func</summary>
			///<param name='sidebar'>sidebar</param>
			///<param name='contextParams'>window (if called from layout view), document (if called from form rendered in iframe)
			///  or other object with IOM context properties set</param>
			///<returns>void</returns>
			try {
				contextParams = Object.assign(this.utils.getDefaultContextItem(), contextParams);
				return this.dataLoader.loadCommandBarImplementation(contextParams.locationName, contextParams, async).then(function(items) {
					if (items.length < 1) {
						return;
					}

					var cuiSidebarItems = [];
					var controlEventParams = this.utils.createClientMethodParams(contextParams);
					for (var i = 0; i < items.length ; ++i) {
						var item = items[i];

						var rtn;
						// name is used as controlId
						var name = item.selectSingleNode('name').text;
						var initMethodName = this.utils.getOnInitHandlerName(item);
						if (initMethodName) {
							contextParams.controlId = name;
							rtn = this.utils.evalCommandBarItemMethod(initMethodName, contextParams);
							if (rtn && rtn.hasOwnProperty('cui_visible') && !rtn['cui_visible']) {
								continue;
							}
						}

						var sidebarItem = {};
						sidebarItem.id = item.getAttribute('id');
						sidebarItem.name = name;
						sidebarItem.label = aras.getItemProperty(item, 'label');

						// Special logic for tooltipTemplate
						// There is should be possibility to set empty tooltip template
						var tooltipTemplateNode = item.selectSingleNode('tooltip_template');
						if (tooltipTemplateNode) {
							sidebarItem.tooltipTemplate = tooltipTemplateNode.text;
							if (!sidebarItem.tooltipTemplate && tooltipTemplateNode.getAttribute('is_null') === '1') {
								sidebarItem.tooltipTemplate = null;
							}
						}

						var additionalData = this.utils.getCommandBarItemAdditionalData(item, rtn);
						sidebarItem.additionalData = additionalData;
						sidebarItem.baseClass = additionalData ? additionalData['cui_base_class'] : null;
						sidebarItem.group = aras.getItemProperty(item, 'group_id');
						sidebarItem.iconClass = (additionalData ? additionalData['cui_icon_class'] : null) || 'sidebarButtonIcon';
						sidebarItem.image = aras.getItemProperty(item, 'image');
						sidebarItem.lcItemType = item.getAttribute('type').toLowerCase();
						sidebarItem.parent = aras.getItemProperty(item, 'parent_menu');
						sidebarItem.events = {
							onClickHandler: this.utils.getHandlerName(item, additionalData, 'on_click_handler'),
							mouseEnter: this.utils.getHandlerName(item, additionalData, 'mouse_enter'),
							mouseLeave: this.utils.getHandlerName(item, additionalData, 'mouse_leave'),
							controlEventParams: controlEventParams
						};

						cuiSidebarItems.push(sidebarItem);
					}

					return cuiSidebarItems;
				}.bind(this));
			}
			catch (e) {
				aras.AlertError('loadSidebar: ' + e);
			}
		});

		this.private.declare('setEventToSidebarItem', function(widget, methodName, eventName, handlerName, controlEventParams) {
			if (methodName) {
				var params = {
					control: widget,
					eventName: eventName,
					handlerName: handlerName
				};
				params = Object.assign(params, controlEventParams);
				on(widget, eventName, this._getEventHandler(this, methodName, eventName, params));
			}
		});
	}

	CuiSidebar.prototype.dispatchCommandBarLoadedEvent = function(locationName, commandBar) {
		var evnt = document.createEvent('Event');
		evnt.locationName = locationName;
		evnt.changeType = 'loaded';
		evnt.commandBar = commandBar;
		evnt.initEvent('commandBarChanged', true, false);
		document.dispatchEvent(evnt);
	};

	CuiSidebar.prototype.loadSidebar = function(contextParams) {
		return this.private.loadSidebarImplementation(contextParams, false);
	};

	CuiSidebar.prototype.loadSidebarAsync = function(contextParams) {
		return this.private.loadSidebarImplementation(contextParams, true);
	};

	CuiSidebar.prototype.initSidebar = function(sidebar, sidebarItems) {
		if (sidebar.get('loaded')) {
			return;
		}

		var widgets = [];
		for (var i = 0; i < sidebarItems.length; ++i) {
			var item = sidebarItems[i];
			var widget = null;
			if (dijit.byId(item.name)) {
				continue;
			}
			var args = {
				id: item.name
			};
			try {
				switch (item.lcItemType) {
					case 'commandbarbutton':
						args.iconClass = item.iconClass;
						args.baseClass = item.baseClass || 'sidebarButton';
						widget = new dijit.form.Button(args);
						break;
					case 'commandbarmenu':
						args.iconClass = item.iconClass;
						args.baseClass = item.baseClass || 'sidebarButton';
						args.dropDownPosition = ['after'];
						var dropDownMenu = new DropDownMenu({
							baseClass: 'sidebarPopup'
						});
						if (item.parent) {
							args.label = item.label || '';
							args.popup = dropDownMenu;
							widget = new dijit.PopupMenuItem(args);
						} else {
							args.dropDown = dropDownMenu;
							widget = new dijit.form.DropDownButton(args);
						}
						widgets[item.id] = args.id; // only for menus with children. args.id is item.name
						break;
					case 'commandbarmenubutton':
						args.iconClass = item.iconClass;
						args.baseClass = item.baseClass || 'sidebarButton';
						args.label = item.label || '';
						widget = new dijit.MenuItem(args);
						break;
					case 'commandbarmenucheckbox':
						args.label = item.label || '';
						if (item.additionalData && item.additionalData['cui_checked']) {
							args.checked = true;
						}
						if (item.group) {
							args.group = item.group;
							widget = new RadioButtonMenuItem(args);
						} else {
							widget = new dijit.CheckedMenuItem(args);
						}
						break;
					case 'commandbarmenuseparator':
						widget = new dijit.MenuSeparator(args);
						break;
				}
			}
			catch (e) {
				aras.AlertError('InitSidebar: ' + e);
				widget = null;
			}
			if (!widget) {
				continue;
			}

			this.utils.applyAdditionalData(widget, item.additionalData, false);
			if (item.image) {
				widget.domNode.querySelector('.' + item.iconClass).style.backgroundImage = 'url("' + item.image + '")';
			}

			this.initSidebarItemEvents(widget, item.events);
			if (item.parent) {
				var parentWidget = dijit.byId(widgets[item.parent]);
				if (parentWidget.popup) {
					parentWidget.popup.addChild(widget);
				} else {
					parentWidget.dropDown.addChild(widget);
				}
			} else {
				sidebar.addChild(widget);
			}

			if (item.tooltipTemplate || item.label) {
				this.setTooltip(widget.id, {template: item.tooltipTemplate, label: item.label});
				if (item.lcItemType == 'commandbarmenu') {
					var tooltipWidget = dijit.byId(widget.id + '_tooltip');
					if (tooltipWidget) {
						tooltipWidget.onShow = this.makeOnShowHandlerForCommandBarMenuTooltip(widget, tooltipWidget);
						widget.onClick = this.makeOnClickHandlerForCommandBarMenu(tooltipWidget);
					}
				}
			}
		} // for

		sidebar.set('loaded', true);
	};

	CuiSidebar.prototype._mapHandler = function(widget, item, additionalData, contextParams, handlerName, eventName) {
		var methodName = this.utils.getHandlerName(item, additionalData, handlerName);
		var controlEventParams = this.utils.createClientMethodParams(contextParams);
		this.private.setEventToSidebarItem(widget, eventName, handlerName, controlEventParams);
	};

	CuiSidebar.prototype.initSidebarItemEvents = function(widget, events) {
		var assignHandler = (function(methodName, handlerName, eventName) {
			this.private.setEventToSidebarItem(widget, methodName, eventName, handlerName, events.controlEventParams);
		}).bind(this);

		assignHandler(events.onClickHandler, 'on_click_handler', 'click');
		assignHandler(events.mouseEnter, 'mouse_enter', mouse.enter);
		assignHandler(events.mouseLeave, 'mouse_leave', mouse.leave);
	};

	CuiSidebar.prototype._mapOnClickHandler = function(widget, item, contextParams) {
		this._mapHandler(widget, item, null, contextParams, 'on_click_handler', 'click');
	};

	CuiSidebar.prototype._getEventHandler = function(self, methodName, eventName, controlEventParams) {
		return function() {
			var rtn = self.utils.evalCommandBarItemMethod(methodName, controlEventParams, true);
			if (!rtn || !rtn['cui_event_sent']) {
				var evnt = document.createEvent('Event');
				evnt.locationName = controlEventParams.locationName;
				evnt.changeType = eventName;
				if (controlEventParams.control) {
					evnt.commandBarTarget = controlEventParams.control.id;
				}
				if (controlEventParams['cui_item']) {
					evnt.commandBarTarget = controlEventParams['cui_item'].getProperty('name');
				}
				evnt.initEvent('commandBarChanged', true, false);
				document.dispatchEvent(evnt);
			}
		};
	};

	return CuiSidebar;
})();

/** ..\Modules\aras.innovator.CUI\Scripts\Classes\CuiShortcuts.js **/
var CuiShortcuts = (function() {
	function CuiShortcuts() {
		//'private' object must be created at ConfigurableUI module.
		//If CuiShortcuts module is used separately from ConfigurableUI module, 'private' object should be created in CuiShortcuts constructor
		if (!this.private) {
			var self = this;
			this.private = {
				declare: function(fieldName, func) {
					var boundFunc = func.bind(self);
					this[fieldName] = boundFunc;
				}
			};
		}

		this.private.declare('loadShortcutsImplementation', function(loadParams, settings, async) {
			if (settings.windows) {
				loadParams = Object.assign(this.utils.getDefaultContextItem(), loadParams);
				return this.dataLoader.loadCommandBarImplementation(loadParams.locationName, loadParams, async).then(function(items) {
					// There is need to unsubscribe all shortcuts. It's necessary because shortcuts should load per itemtype.
					// Each itemtype can have own shortcuts sequence.
					// 'skipShortcutsUnload' is a special flag that prevent unloading shortcuts from context defined in settings.
					// For example: Tear-Off window with relationships grid. Shortcuts are registred at same context but for different Loactions:
					// 'ItemWindowRelationshipsShortcuts' and 'ItemWindowShortcuts' (please look at Relationships.js 'registerShortcuts' method)
					// 'skipShortcutsUnload' is 'undefined' by default.
					if (!settings.skipShortcutsUnload) {
						this.unloadShortcuts(settings);
					}

					for (var i = 0; i < items.length; i++) {
						var currentItem = items[i];
						var handler = this._getShortcutHandler(currentItem);
						var shortcut = currentItem.selectSingleNode('shortcut');
						shortcut = shortcut ? shortcut.text : '';
						if (handler) {
							var shortcutCallback = {handler: handler, shortcut: shortcut};
							var initMethodName = this.utils.getOnInitHandlerName(currentItem);
							var initData = null;
							if (initMethodName) {
								initData = this.utils.evalCommandBarItemMethod(initMethodName, loadParams);
							}

							var additionalData = this.utils.getCommandBarItemAdditionalData(currentItem, initData);
							if (additionalData) {
								Object.assign(shortcutCallback, additionalData);
							}

							for (var j = 0; j < settings.windows.length; j++) {
								shortcutCallback.context = settings.context;
								aras.shortcutsHelperFactory.getInstance(settings.windows[j]).subscribe(shortcutCallback, settings.registerChildFrames);
							}
						}
					}
				}.bind(this));
			}
		});
	}

	CuiShortcuts.prototype._getShortcutHandler = function(item) {
		var methodId = item.selectSingleNode('on_click_handler');
		methodId = methodId ? methodId.text : '';
		var evalShortcutHandler = function evalevalShortcutHandler(state) {
			var methodNd = aras.MetadataCache.GetClientMethodNd(methodId, 'id');
			if (methodNd) {
				var methodCode = methodNd.selectSingleNode('method_code');
				if (methodCode) {
					/* jshint ignore:start */
					var newFunc = new Function('state', methodCode.text);
					/* jshint ignore:end */
					return newFunc.call(this, state);
				}
			}
			return;
		};

		return methodId ? evalShortcutHandler : null;
	};

	CuiShortcuts.prototype.loadShortcutsFromCommandBars = function(loadParams, settings) {
		this.private.loadShortcutsImplementation(loadParams, settings, false);
	};

	CuiShortcuts.prototype.loadShortcutsFromCommandBarsAsync = function(loadParams, settings) {
		return this.private.loadShortcutsImplementation(loadParams, settings, true);
	};

	CuiShortcuts.prototype.unloadShortcuts = function(settings) {
		for (var i = 0; i < settings.windows.length; i++) {
			var currentWindow = settings.windows[i];
			var scHelper = aras.shortcutsHelperFactory.getInstance(currentWindow);
			scHelper.unsubscribeWindow(settings.context);
		}
	};

	return CuiShortcuts;
})();

/** ..\Modules\aras.innovator.CUI\Scripts\Classes\CuiMenu.js **/
var CuiMenu = (function() {
	this.aspect;
	require(['dojo/aspect'],
		function(_aspect) {
			aspect = _aspect;
		});

	function CuiMenu() {
		this.menusDict = [];
		//'private' object must be created at ConfigurableUI module.
		//If CuiMenu module is used separately from ConfigurableUI module, 'private' object should be created in CuiMenu constructor
		if (!this.private) {
			var self = this;
			this.private = {
				declare: function(fieldName, func) {
					var boundFunc = func.bind(self);
					this[fieldName] = boundFunc;
				}
			};
		}

		this.private.declare('getExistMenuBarIdImplementation', function(locationName, contextParams, async) {
			var hash = this.menusDict[contextParams.menuId];
			if (hash) {
				return async ? Promise.resolve(hash) : ArasModules.SyncPromise.resolve(hash);
			}

			return this.dataLoader.loadCommandBarImplementation(locationName, contextParams, async).then(function(items) {
				// using context.xml for MSXML node list
				var xml = items.context ? items.context.xml :
					items.map(function(elt) { return elt.xml; }).join();

				var hash = this.utils.getHashCode(xml);
				this.menusDict[contextParams.menuId] = hash;
				return hash;
			}.bind(this));
		});

		// Dictionary of menu items. Id is used as key
		this.private.menuItemsById = {};

		this.private.declare('loadMenuImplementation', function(locationName, menuContext, async) {
			var contextParams = Object.assign(this.utils.getDefaultContextItem(), menuContext);

			return this.dataLoader.loadCommandBarImplementation(locationName, contextParams, async).then(function(items) {
				var i = 0;

				// Create array of all CommandBarItems
				var itemsArray = [];
				for (i = 0; i < items.length ; i++) {
					var currentItem = items[i];
					var name = aras.escapeXMLAttribute(currentItem.selectSingleNode('name').text);
					var idx = currentItem.getAttribute('id');
					var label = currentItem.selectSingleNode('label');
					label = label ? label.text : '';
					var image = currentItem.selectSingleNode('image');
					image = image ? image.text : '';
					var groupId = currentItem.selectSingleNode('group_id');
					groupId = groupId ? groupId.text : '';
					var parentMenu = currentItem.selectSingleNode('parent_menu');
					parentMenu = parentMenu ? parentMenu.text : '';
					var includeEvents = currentItem.selectSingleNode('include_events');
					includeEvents = includeEvents ? includeEvents.text : '';
					var additionalData = currentItem.selectSingleNode('additional_data');
					additionalData = additionalData ? additionalData.text : '';

					var menuItem = {
						name: name,
						label: label ? aras.escapeXMLAttribute(label) : name,
						id: idx,
						type: currentItem.getAttribute('type'),
						image: image,
						group: groupId,
						parentMenuId: parentMenu,
						additionalData: additionalData,
						includeEvents: includeEvents,
						onClick: aras.getItemPropertyAttribute(currentItem, 'on_click_handler', 'keyed_name'),
						onInit: aras.getItemPropertyAttribute(currentItem, 'on_init_handler', 'keyed_name')
					};
					itemsArray.push(menuItem);
					this.private.menuItemsById[idx] = menuItem;
				}

				var menuItems = [];
				// Currently supported only one root menubar. Related issue IR-038695 "CUI: Can't add Menu without parent to Main Window Main Menu"
				// Create object for menu with submenus as childs.
				for (i = 0; i < itemsArray.length; i++) {
					if (!itemsArray[i].parentMenuId) {
						var rootItem = itemsArray[i];
						rootItem.childs = this._getChildMenus(rootItem.id, itemsArray);
						menuItems.push(itemsArray[i]);
					}
				}

				var showMenuId = (this.menusDict[contextParams.menuId] || locationName);
				var xml = '<menuapplet show="' + showMenuId + '">' +
							'<menubar id="' + locationName + '" name="' + locationName + '">' +
								this._loadMenuFromCommandBars(menuItems, contextParams) +
							'</menubar>' +
						'</menuapplet>';

				return xml;
			}.bind(this));
		});
	}

	CuiMenu.prototype.getExistMenuBarId = function(locationName, contextParams) {
		var hash;
		this.private.getExistMenuBarIdImplementation(locationName, contextParams, false).then(function(res) {
			hash = res;
		});
		return hash;
	};

	CuiMenu.prototype.getExistMenuBarIdAsync = function(locationName, contextParams) {
		return this.private.getExistMenuBarIdImplementation(locationName, contextParams, true);
	};

	CuiMenu.prototype.loadMenuAppletFromCommandBars = function(locationName, menuContext) {
		var xml;
		this.private.loadMenuImplementation(locationName, menuContext, false).then(function(res) {
			xml = res;
		});
		return xml;
	};

	CuiMenu.prototype.loadMenuFromCommandBarsAsync = function(locationName, menuContext) {
		return this.private.loadMenuImplementation(locationName, menuContext, true);
	};

	CuiMenu.prototype._getChildMenus = function(rootId, allItems) {
		var childs = [];
		for (var i = 0; i < allItems.length; i++) {
			var item = allItems[i];
			if (rootId === item.parentMenuId) {
				var childsOfCurrentItem = this._getChildMenus(item.id, allItems);
				if (childsOfCurrentItem.length > 0) {
					item.childs = childsOfCurrentItem;
				}
				childs.push(item);
			}
		}
		return childs;
	};

	CuiMenu.prototype._loadMenuFromCommandBars = function(items, contextParams) {
		var xml = '';
		for (var i = 0; i < items.length; i++) {
			var item = items[i];
			var initData = null;
			if (item.onInit) {
				var initContextParams = {control: item};
				initContextParams = Object.assign(initContextParams, contextParams);
				initData = this.utils.evalCommandBarItemMethod(item.onInit, initContextParams);
			}

			var additionalData = this.utils._getCommandBarItemAdditionalData(item.additionalData, initData);

			var attributesMapping = {'icon': item.image, 'idx': item.id, 'id': item.name, 'name': item.label};
			if (additionalData) {
				attributesMapping.disabled = additionalData['cui_disabled'];
				attributesMapping.invisible = additionalData['cui_invisible'];
				attributesMapping.checked = additionalData['cui_checked'];
				attributesMapping.style = additionalData['cui_style'];
				attributesMapping.class = additionalData['cui_class'];
			}

			var attributes = this.utils._mapExtraControlPropsToXml(attributesMapping);
			switch (item.type) {
				case 'CommandBarMenu':
					var res = !item.childs ? '' : this._loadMenuFromCommandBars(item.childs, contextParams);
					xml += this.utils.format('<menu {0}>', attributes) + res + '</menu>';
					break;
				case 'CommandBarMenuButton':
					xml += this.utils.format('<item {0} />', attributes);
					break;
				case 'CommandBarMenuCheckbox':
					xml += this.utils.format('<{0} {1} group="{2}" />', item.group ? 'radioitem' : 'checkitem', attributes, item.group);
					break;
				case 'CommandBarSeparator':
				case 'CommandBarMenuSeparator':
					xml += this.utils.format('<separator {0}/>', attributes);
					break;
			}
		}
		return xml;
	};

	CuiMenu.prototype.callInitHandlersForMenu = function(eventState, eventType) {
		var menuPromise;
		var topWindow = aras.getMostTopWindowWithAras(window);
		var contextParams = {eventState: eventState, eventType: eventType, isReinit: true};
		if (topWindow.isTearOff) {
			contextParams.itemId = topWindow.itemID;
			if (topWindow.itemType) {
				contextParams.itemTypeId = topWindow.itemType.getAttribute('id');
			}

			menuPromise = topWindow.tearOffMenuController ? topWindow.tearOffMenuController.when('MainMenuInitialized') : Promise.resolve();
		} else if (topWindow.work && topWindow.work.menu && topWindow.work.menu.menuApplet) {
			var workFrame = topWindow.work;
			contextParams.itemTypeId = workFrame.itemTypeID;
			if (workFrame.grid) {
				contextParams.itemId = workFrame.grid['getSelectedId_Experimental']();
			}

			menuPromise = Promise.resolve(topWindow.work.menu.menuApplet);
		}

		if (menuPromise) {
			menuPromise.then(function(menu) {
				var activeMenuBar = menu.getMenuBarById(menu.activeMenuBarId);
				var handleNestedMenu = (function(parentMenuWidget) {
					for (var i = 0; i < parentMenuWidget.getItemsCount(); i++) {
						var widget = parentMenuWidget.getItemAt(i);
						runOnInitHandler(widget);
					}
				}).bind(this);

				var runOnInitHandler = (function(widget) {
					var itemId = widget.item.get('idx');
					var item = this.private.menuItemsById[itemId];
					// item could be undefined because not all controls are created through CUI (for example separator at Actions menu).

					if (item && item.includeEvents && item.includeEvents.indexOf(eventType) !== -1 && item.onInit) {
						var initContextParams = {control: item};
						initContextParams = Object.assign(initContextParams, contextParams);
						var reinitData = this.utils.evalCommandBarItemMethod(item.onInit, initContextParams);
						if (reinitData) {
							if (reinitData['cui_class']) {
								widget.item.domNode.classList.add(reinitData['cui_class']);
								delete reinitData['cui_class'];
							}
							var domNodeForRestyle = widget.item.domNode;
							domNodeForRestyle.style.display = reinitData['cui_invisible'] ? 'none' : '';
							delete reinitData['cui_invisible'];

							if (reinitData['cui_style']) {
								var cuiStyle = reinitData['cui_style'].split(';');

								for (var j = 0; j < cuiStyle.length; j++) {
									var trimmedStyle = cuiStyle[j].trim();
									if (trimmedStyle) {
										var keyValue = trimmedStyle.split(':');
										domNodeForRestyle.style[keyValue[0].trim()] = keyValue[1].trim();
									}
								}

								delete reinitData['cui_style'];
							}

							if (reinitData['cui_disabled'] !== undefined) {
								widget.item.set('disabled', reinitData['cui_disabled']);
								delete reinitData['cui_disabled'];
							}

							if (reinitData['cui_checked'] !== undefined) {
								widget.setState(reinitData['cui_checked']);
								delete reinitData['cui_checked'];
							}

							var keys = Object.keys(reinitData);
							for (var i = 0; i < keys.length; i++) {
								var key = keys[i];
								widget.item.set(key, reinitData[key]);
							}
						}
					}

					handleNestedMenu(widget);
				}).bind(this);

				for (var i = 0; i < activeMenuBar.length; i++) {
					var parentMenuNode = activeMenuBar[i];
					var parentMenuId = parentMenuNode.id;
					var parentMenuWidget = menu.findMenu(parentMenuId);

					runOnInitHandler(parentMenuWidget);
				}
			}.bind(this));
		}
	};

	CuiMenu.prototype.resetMenuCache = function() {
		this.menusDict = [];
		aras.MetadataCache.DeleteConfigurableUiDatesFromCache();
	};

	CuiMenu.prototype.initMenuEvents = function(menu, params) {
		var self = this;
		var runHandler = function(menuItem, type) {
			var itemId = menuItem.item.idx || menuItem.item.get('idx');
			var item = self.private.menuItemsById[itemId];
			if (item && item.onClick) {
				aras.evalMethod(item.onClick, '', menuItem);
			} else if (params && params[type]) {
				params[type](menuItem);
			}
		};

		clientControlsFactory.on(menu, {
			'onSelect': function(menuItem) {
				runHandler(menuItem, 'onSelect');
			},
			'onCheck': function(menuItem) {
				runHandler(menuItem, 'onCheck');
			}
		});

		aspect.around(menu, 'findItem', function(compatibilityFindItemAspect) {
			return function(id) {
				var menuItem = compatibilityFindItemAspect(id);
				if (!menuItem && params) {
					menuItem = compatibilityFindItemAspect(params.prefix + id);
				}

				return menuItem;
			};
		});
	};

	return CuiMenu;
})();

/** ..\Modules\aras.innovator.CUI\Scripts\Classes\CuiDataLoader.js **/
var CuiDataLoader = (function() {
	var blankText = {text: ''};
	const dataCache = {};

	function CuiDataLoader() {
		this.utils = new CuiUtils();
	}

	function isPresentableItem(itemTypeId) {
		if (!itemTypeId) {
			return false;
		}
		var item = aras.getItemTypeForClient('PresentableItems', 'name');
		var morphaeList = aras.getMorphaeList(item.node);
		return morphaeList.some(function(item) {
			return item.id === itemTypeId;
		});
	}

	CuiDataLoader.prototype.getCommandBarDependencies = function(locationName, contextItem) {
		///<summary>
		///Accepts same context params as GetCommandBarItems.
		///Calls client GetCommandBarDependencies method that returns bool indicating is corresponding configurable
		///  UI dependent of missing context params (now serves only itemID skipping for caching)
		///</summary>
		return aras.evalMethod('GetCommandBarDependencies', '', this.getRequestParams(locationName, contextItem));
	};

	// do not use null, use '' for (server method/cache) params; todo: causes trapped exc. e.g., on TWMM
	CuiDataLoader.prototype.getRequestParams = function(locationName, contextItem) {
		///<summary>
		///For cache request and related dependency check
		///</summary>
		var classification = contextItem['item_classification'] ||
			(contextItem.item && contextItem.item.nodeType === 1 ?
				(contextItem.item.selectSingleNode('Item/classification') || blankText).text
				: ''
			);
		var itemTypeId = contextItem.itemType ? contextItem.itemType.getAttribute('id') : '';
		return {
			'item_id': isPresentableItem(itemTypeId) ? contextItem.itemID : '',
			'item_type_id': itemTypeId,
			'location_name': locationName, 'item_classification': classification
		};
	};

	CuiDataLoader.prototype.loadCommandBar = function(locationName, contextItem, contextParams) {
		///<summary>
		///Loads on server, then applies client builder methods. Doesn't use cache if config is item dependent
		///</summary>
		/// <param name='locationName'></param>
		/// <param name='contextParams'>Object with context-specific properties</param>
		///<returns>CommandBarItem(s)</returns>
		var res;
		this.loadCommandBarImplementation(locationName, contextItem, false, contextParams).then(function(items) {
			res = items;
		});
		return res;
	};

	CuiDataLoader.prototype.loadCommandBarAsync = function(locationName, contextItem) {
		return this.loadCommandBarImplementation(locationName, contextItem, true);
	};

	CuiDataLoader.prototype.loadCommandBarImplementation = function(locationName, contextItem, async, contextParams) {
		var getConfigurableUiItemIsDependent = function(contextItem) {
			var items = aras.newIOMItem('Method', 'GetCommandBarItems');
			if (contextItem.itemID) {
				items.setProperty('item_id', contextItem.itemID);
			}
			if (contextItem.itemType) {
				items.setProperty('item_type_id', contextItem.itemType.getAttribute('id'));
			}
			items.setProperty('location_name', locationName);
			if (contextItem.item) {
				items.setProperty('item_classification', (contextItem.item.selectSingleNode('Item/classification') || blankText).text);
			}
			items = items.apply();
			return items.dom;
		};

		contextItem = contextItem || this.utils.getDefaultContextItem();
		var requestParams = this.getRequestParams(locationName, contextItem);
		var isItemDependent = this.getCommandBarDependencies(locationName, contextItem);

		return (function() {
			var items;
			if (async) {
				const requestParamsKey = requestParams.item_type_id + requestParams.location_name + requestParams.item_classification + requestParams.item_id;
				dataCache[requestParamsKey] = dataCache[requestParamsKey] || new Promise(function(resolve) {
					if (!isItemDependent) {
						aras.MetadataCache.GetConfigurableUiAsync(requestParams).then(function(cuiItems) {
							items = cuiItems.getResult();
							resolve(items);
						});
					} else {
						items = getConfigurableUiItemIsDependent(contextItem);
						resolve(items);
					}
				}).then(function(items) {
					dataCache[requestParamsKey] = undefined;
					return items;
				});
				return dataCache[requestParamsKey];
			} else {
				return new ArasModules.SyncPromise(function(resolve) {
					if (!isItemDependent) {
						var cuiItems = aras.MetadataCache.GetConfigurableUi(requestParams);
						items = cuiItems.getResult();
					} else {
						items = getConfigurableUiItemIsDependent(contextItem);
					}
					resolve(items);
				});
			}
		})().then(function(items) {
			return this.applyClientBuilders(items, contextItem, contextParams);
		}.bind(this));
	};

	CuiDataLoader.prototype.applyClientBuilders = function(itemsNode, contextItem, contextParams) {
		var i;
		// find & apply client builder method
		// may be necessary for builder method
		Object.defineProperty(contextItem, 'cui_items', {
			get: function() {
				var iomItem = aras.IomInnovator.newItem();
				if (itemsNode) {
					iomItem.loadAML(itemsNode.xml);
				} else {
					iomItem.loadAML('<AML/>');
				}
				return iomItem;
			},
			enumerable: true
		});

		var hasClientBuilderMethod = false;
		var barSectionsDict = {};

		var itemsArray = [];
		items = itemsNode.selectNodes('Item|AML/Item|//Result/Item');
		var itemsCount = items.length;

		// stage 1
		for (i = 0; i < itemsCount; ++i) {
			var item = items[i];
			var isCBarSection = item.getAttribute('type') == 'CommandBarSection';
			barSectionsDict[i] = isCBarSection;

			if (isCBarSection) {
				hasClientBuilderMethod = true;
			}
		}

		if (!hasClientBuilderMethod) {
			return items;
		}

		var itemsArr = [];

		// stage 2
		for (i = 0; i < itemsCount; ++i) {
			if (!barSectionsDict[i]) {
				itemsArr.push(items[i]);
			}
		}
		// stage 3
		for (i = 0; i < itemsCount; ++i) {
			if (barSectionsDict[i]) {
				var getBuildMethodKeyedName;
				var builderMethod = items[i].selectSingleNode('builder_method');
				getBuildMethodKeyedName = builderMethod ? builderMethod.getAttribute('keyed_name') : null;
				var sectionItems;
				if (items) {
					sectionItems = this.utils.evalCommandBarItemMethod(getBuildMethodKeyedName, contextItem, null, contextParams);
				}
				if (this.utils.noItems(sectionItems)) {
					continue;
				}

				// Convert IOM item to XML nodes list
				// XML-document is created in the context of the current window
				// faster than IOM items from main window

				doc = XmlDocument();
				doc.loadXML(sectionItems.dom.xml);
				sectionItems = doc.selectNodes('//Item');

				for (var m = 0; m < sectionItems.length ; ++m) {
					var control = sectionItems[m];
					if (!control.getAttribute('type')) {
						continue;
					}
					var index = -1;
					var k;
					var sortOrder = control.selectSingleNode('sort_order'); // if NaN for undefined, will be just added
					sortOrder = sortOrder ? sortOrder.text : null;
					sortOrder = parseInt(sortOrder);
					var id = control.getAttribute('id');
					var action = control.selectSingleNode('action');
					action = action ? action.text : 'Add';
					switch (action) {
						case 'ClearAll':
							itemsArr = [];
							break;
						case 'Remove':
							for (k = itemsArr.length - 1; k >= 0; --k) {
								if (itemsArr[k].getAttribute('id') === id) {
									itemsArr.splice(k, 1);
									break;
								}
							}
							break;
						case 'Replace':
							for (k = 0; k < itemsArr.length; ++k) {
								var alternate = control.selectSingleNode('alternate');
								alternate = alternate ? alternate.text : null;
								if (itemsArr[k].getAttribute('id') === alternate) {
									itemsArr[k] = control;
								}
							}
							break;
						case 'Add':
							for (k = 0; k < itemsArr.length; ++k) {

								var itemSortOrder = itemsArr[k].selectSingleNode('sort_order');
								itemSortOrder = itemSortOrder ? itemSortOrder.text : null;
								if (itemSortOrder > sortOrder) {
									index = k;
									break;
								}
							}

							if (index > -1) {
								itemsArr.splice(index, 0, control);
							} else {
								itemsArr.push(control);
							}
							break;
						default:
							break;
					}
				}
			}
		}

		if (itemsArr.length === 0) {
			return aras.IomInnovator.newError('No items found');
		}

		return itemsArr;
	};

	return CuiDataLoader;
})();

/** ..\Modules\aras.innovator.CUI\Scripts\Classes\CuiContextMenu.js **/
var CuiContextMenu = (function() {
	var aspect;
	require(['dojo/aspect'],
		function(_aspect) {
			aspect = _aspect;
		});

	function CuiContextMenu() {
		if (!this.private) {
			this.private = {
				declare: function(fieldName, func) {
					var boundFunc = func.bind(self);
					this[fieldName] = boundFunc;
				}
			};
		}
		this.private.aspectItems = [];
		this.private.popupMenuReinitDataById = {};

		this.private.declare('_getDataForPopupMenu', function(popupMenu, items, itemStates, contextParams, contextItem) {
			const onClickHandlerMap = {};
			const menuItemsList = {};
			let isPreviousSeparator = false;
			for (let i = 0; i < items.length ; i++) {
				const item = items[i];
				const type = item.getAttribute('type');
				if (!type) {
					continue;
				}
				const isSeparator = type.toLowerCase() === 'commandbarseparator' || type.toLowerCase() === 'commandbarmenuseparator';

				// logic to prevent showing two consecutive separators
				if (isSeparator) {
					if (isPreviousSeparator) {
						continue;
					} else {
						isPreviousSeparator = true;
					}
				}

				const commandIdNode = item.selectSingleNode('name');
				let commandId = commandIdNode ? commandIdNode.text : '';

				const initMethodName = this.utils.getOnInitHandlerName(item);
				this.private.popupMenuReinitDataById[commandId] = {handler: initMethodName, cuiItem: item};

				if (!itemStates || itemStates[commandId] || itemStates[commandId] === undefined) {
					const iconNode = item.selectSingleNode('image');
					const icon = iconNode ? iconNode.text : '';
					let initData = null;
					if (initMethodName) {
						contextItem.controlId = commandId;
						contextItem.contextParams = contextParams;
						contextItem.additionalData = this.utils.getCommandBarItemAdditionalData(item, null);
						initData = this.utils.evalCommandBarItemMethod(initMethodName, contextItem);
					}
					const additionalData = this.utils.getCommandBarItemAdditionalData(item, initData);
					let label = null;
					if (!isSeparator) {
						const labelNode = item.selectSingleNode('label');
						label = labelNode ? labelNode.text : '';
						if (!label && additionalData && additionalData['cui_resource_key']) {
							label = aras.getResource(additionalData['cui_resource_solution'] || '', additionalData['cui_resource_key']);
						}
						const clickHandler = this.utils.getOnClickHandler(item);
						if (clickHandler) {
							onClickHandlerMap[commandId] = clickHandler;
						}
						isPreviousSeparator = false;
					}

					let key = item.getAttribute('id') || commandId;
					// Separator without id and name can be obtained from builder method. So some identificator is needed to distinguish separators
					if (!key && isSeparator) {
						commandId = key = 'separator' + i;
					}
					const parentElementId = this.utils.getParentMenuId(item);
					const isItemDisabled = additionalData && (additionalData.disabled || additionalData['cui_disabled']);
					menuItemsList[key] = {
						id: commandId,
						name: label || commandId,
						icon: icon,
						parentId: parentElementId,
						disable: isItemDisabled,
						additionalData: additionalData,
						separator: isSeparator
					};
				}
			}
			const menuData = [];
			for (let key in menuItemsList) {
				const menuItem = menuItemsList[key];
				const parentElementId = menuItem.parentId;
				if (parentElementId) {
					const parentElement = menuItemsList[parentElementId];
					if (parentElement) {
						if (!parentElement.subMenu) {
							parentElement.subMenu = [];
						}
						parentElement.subMenu.push(menuItem);
					}
				} else {
					menuData.push(menuItem);
				}
			}
			popupMenu.onClickHandlerMap = onClickHandlerMap;
			delete contextItem.controlId;

			return {
				dataList: menuItemsList,
				dataTree: menuData
			};
		});

		this.private.declare('_setPopupMenuItemsVisibility', function(popupMenu, menuItemsList) {
			for (let key in menuItemsList) {
				const menuItem = menuItemsList[key];
				if (menuItem.additionalData) {
					const isInvisible = menuItem.additionalData.hidden || menuItem.additionalData['cui_invisible'];
					if (isInvisible) {
						if (menuItem.separator) {
							popupMenu.setHideSeparator(menuItem.id, isInvisible);
						} else {
							popupMenu.setHide(menuItem.id, isInvisible);
						}
					}
				}
			}
		});
	}

	CuiContextMenu.prototype.initPopupMenu = function(popupMenu, contextItem, contextParams) {
		///<summary>Have to be called right after creating ContextMenu in order to set handlers on the menu and etc.
		///Used for both contextMenu and popupMenu
		///For mainTree.html, ItemGrid, inBasketTaskGrid, relationshipsGrid</summary>
		var customClickHandler = function(commandId, rowId, col) {
			if (this.onClickHandlerMap && this.onClickHandlerMap[commandId]) {
				var clickHandler = this.onClickHandlerMap[commandId];
				var args = {
					commandId: commandId,
					rowId: rowId,
					col: col
				};
				if (contextItem) {
					args.contextItem = contextItem;
				}
				if (contextParams) {
					args.contextParams = contextParams;
				}
				clickHandler(args);
			}
		};
		var aspectItems = this.private.aspectItems.filter(function(item) {
			return item.menu === popupMenu;
		});
		var aspectItem = aspectItems.length && aspectItems[0];
		if (aspectItem) {
			aspectItem.aspect.remove();
			this.private.aspectItems = this.private.aspectItems.filter(function(item) {
				return item !== aspectItem;
			});
		}
		aspectItem = {
			aspect: aspect.after(popupMenu, 'onItemClick', customClickHandler, true),
			menu: popupMenu
		};
		this.private.aspectItems.push(aspectItem);
	};

	CuiContextMenu.prototype.fillContextMenu = function(locationName, contextMenu) {
		///<summary>For mainTree.html</summary>
		var contextItem = this.utils.getDefaultContextItem();
		if (!contextItem.itemType && contextMenu.rowId) {
			var itemTypeFromCache = aras.MetadataCache.GetItemType(contextMenu.rowId, 'name');
			var result = itemTypeFromCache.getResult();
			if (!itemTypeFromCache.isFault() && result.childNodes[0]) {
				contextItem.itemType = result.childNodes[0];
			}
		}

		var items = this.dataLoader.loadCommandBar(locationName, contextItem);
		contextMenu.removeAll();
		if (this.utils.noItems(items)) {
			return;
		}
		var menuData = [];
		var onClickHandlerMap = {};

		for (var i = 0; i < items.length ; ++i) {
			var item = items[i];

			var initMethodName = this.utils.getOnInitHandlerName(item);
			var initData = null;
			if (initMethodName) {
				initData = this.utils.evalCommandBarItemMethod(initMethodName, contextItem);
				if (initData && initData.hasOwnProperty('cui_visible') && !initData['cui_visible']) {
					continue;
				}
			}

			var label = item.selectSingleNode('label');
			label = label ? label.text : '';
			var additionalData = this.utils.getCommandBarItemAdditionalData(item, initData);
			if (!label && additionalData && additionalData['cui_resource_key']) {
				label = aras.getResource(additionalData['cui_resource_solution'] || '', additionalData['cui_resource_key']);
			}

			var controlId = item.selectSingleNode('name');
			controlId = controlId ? controlId.text : '';
			var clickHandler = this.utils.getOnClickHandler(item);
			if (clickHandler) {
				onClickHandlerMap[controlId] = clickHandler;
			}

			menuData.push({id: controlId, name: label || controlId});
		}
		contextMenu.addRange(menuData);
		contextMenu.onClickHandlerMap = onClickHandlerMap;
	};

	CuiContextMenu.prototype.fillPopupMenu = function(locationName, popupMenu, contextItemOverride, itemStates, dontClearMenu, contextParams) {
		///<summary></summary>
		///<param name='locationName'></param>
		///<param name='popupMenu'>Innovator\Client\Modules\components\contextMenu.js instance</param>
		///<param name='contextItemOverride'></param>
		///<param name='itemStates'>id:enabled map</param>
		///<param name='dontClearMenu'></param>
		///<param name='contextParams'></param>
		///<returns>Bool; true if menu should be shown</returns>
		const contextItem = Object.assign(this.utils.getDefaultContextItem(), contextItemOverride);
		const items = this.dataLoader.loadCommandBar(locationName, contextItem, contextParams);
		if (!dontClearMenu) {
			popupMenu.removeAll();
		}

		if (this.utils.noItems(items)) {
			return false;
		}

		const menuData = this.private._getDataForPopupMenu(popupMenu, items, itemStates, contextParams, contextItem);

		popupMenu.addRange(menuData.dataTree);

		this.private._setPopupMenuItemsVisibility(popupMenu, menuData.dataList);
		return true;
	};

	CuiContextMenu.prototype.onGridHeaderContextMenu = function(e, grid, isAtCell) {
		var getCountVisibleColunms = function(grid) {
			var result = 0;
			for (var i = 0; i < grid.getColumnCount(); i++) {
				if (grid.isColumnVisible(i)) {
					result++;
				}
			}
			return result;
		};

		if (e.rowIndex == '-1') {
			var headerMenu = grid['getHeaderMenu_Experimental']();
			if (isAtCell && !headerMenu.initialized) {
				// fill menu if it hasn't items and click was at the header cell
				this.fillPopupMenu('PopupMenuGridHeader', headerMenu);
				// disable 'hideCol' item if number visible columns = 1
				if (headerMenu.collectionMenu && headerMenu.collectionMenu.hideCol && getCountVisibleColunms(grid) === 1) {
					headerMenu.setDisable('hideCol', true);
				}
				if (e.view && e.view.isMainGrid) {
					headerMenu.setHide('insertCol', true);
				}
			} else if (!isAtCell && headerMenu.initialized) {
				// clear menu (don't show) if menu has items and click was not at the header cell
				headerMenu.removeAll();
			}
			headerMenu.initialized = isAtCell;
		}

		return true;
	};

	CuiContextMenu.prototype.callInitHandlersForPopupMenu = function(eventState, eventType) {
		var topWnd = aras.getMostTopWindowWithAras();
		if (topWnd && topWnd.main && topWnd.main.work && topWnd.main.work.grid) {
			var grid = topWnd.main.work.grid;
			var popupMenu = grid.getMenu();
			var contextParams = {eventState: eventState, eventType: eventType, isReinit: true};
			var doReinit = (function(collectionName, isSeparator) {
				var menuItemsIds = Object.keys(popupMenu[collectionName]);
				for (var i = 0; i < menuItemsIds.length; i++) {
					var id = menuItemsIds[i];
					var menuItem = popupMenu[collectionName][id];

					var reinitData = this.private.popupMenuReinitDataById[id];
					if (reinitData && reinitData.cuiItem && reinitData.handler) {
						var additionalDataNode = reinitData.cuiItem.selectSingleNode('additional_data');
						var additionalData = additionalDataNode ? additionalDataNode.text : '';

						contextParams.control = {item: menuItem, additionalData: additionalData};
						reinitData = this.utils.evalCommandBarItemMethod(reinitData.handler, contextParams);
						if (reinitData) {
							popupMenu[isSeparator ? 'setHideSeparator' : 'setHide'](id, reinitData['cui_invisible']);
							if (!isSeparator && reinitData['cui_disabled'] !== undefined) {
								popupMenu.setDisable(id, reinitData['cui_disabled']);
							}
						}
					}
				}
			}).bind(this);

			if (popupMenu) {
				if (popupMenu.collectionMenu) {
					doReinit('collectionMenu');
				}
				if (popupMenu.collectionSeparator) {
					doReinit('collectionSeparator', true);
				}
			}
		}
	};

	return CuiContextMenu;
})();

/** ..\Modules\aras.innovator.CUI\Scripts\Classes\CompatCuiToolbar.js **/
var CompatCuiToolbar = (function() {
	function CompatCuiToolbar() {
		this.toolbarsDict = [];
		//'private' object must be created at ConfigurableUI module.
		//If CompatCuiToolbar module is used separately from ConfigurableUI module, 'private' object should be created in CompatCuiToolbar constructor
		if (!this.private) {
			var self = this;
			this.private = {
				declare: function(fieldName, func) {
					var boundFunc = func.bind(self);
					this[fieldName] = boundFunc;
				}
			};
		}

		this.private.declare('loadToolbarImplementation', function(contextItem, initData, async) {
			/// <returns>XML for toolbar</returns>
			contextItem = Object.assign(this.utils.getDefaultContextItem(), contextItem);
			var promise;
			if (!contextItem.items) {
				if (!contextItem['item_classification']) {
					contextItem['item_classification'] = aras.getItemProperty(contextItem.item, 'classification') || '%all_grouped_by_classification%';
				}

				promise = this.dataLoader.loadCommandBarImplementation(contextItem.locationName, contextItem, async).then(function(items) {
					contextItem.items = items;
					return contextItem;
				});
			} else {
				promise = async ? Promise.resolve(contextItem) : ArasModules.SyncPromise.resolve(contextItem);
			}

			return promise.then(function(contextItem) {
				var xml = this._loadToolbarFromCommandBars(contextItem, initData || {});

				if (contextItem.mainSubPrefix) {
					xml = xml.replace(contextItem.mainSubPrefix, '');
				}

				if (contextItem.subPrefix) {
					xml = xml.replace(contextItem.subPrefix, '');
				}

				contextItem.toolbarApplet.loadToolbarFromStr(xml);
			}.bind(this));
		});

		this.private.declare('getExistToolbarIdImplementation', function(locationName, contextParams, async) {
			var hash = this.toolbarsDict[contextParams.toolbarId];
			if (hash) {
				return async ? Promise.resolve(hash) : ArasModules.SyncPromise.resolve(hash);
			}

			return this.dataLoader.loadCommandBarImplementation(locationName, contextParams, async).then(function(items) {
				// using context.xml for MSXML node list
				var xml = items.context ? items.context.xml :
					items.map(function(elt) { return elt.xml; }).join();
				var hash = this.utils.getHashCode(xml);
				this.toolbarsDict[contextParams.toolbarId] = hash;
				return hash;
			}.bind(this));
		});

		this.private.declare('runOnInitHandler', function(onInitHandler, tbItem, inArgs) {
			try {
				return onInitHandler(tbItem, inArgs);
			} catch (ex) {
				aras.AlertError(aras.getResource('', 'item_methods.event_handler_failed'),
				aras.getResource('../Modules/aras.innovator.cui/', 'cui_on_init_handler_error', ex.description),
				aras.getResource('', 'common.client_side_err'));
			}
		});
	}

	CompatCuiToolbar.prototype.createConfigurableToolbar = function(toolbarId, connectId, locationName, contextParams, contextItemOverride) {
		///<summary>Top-level func</summary>
		///<returns>Bool; true if non-empty toolbar was created</returns>

		var i = 0;
		var contextItem = contextItemOverride || this.utils.getDefaultContextItem();

		var items = this.dataLoader.loadCommandBar(locationName, contextItem);
		if (this.utils.noItems(items)) {
			return Promise.resolve(false);
		}

		var toolbarApplet;
		var self = this;

		var args = {id: toolbarId};
		if (typeof(connectId) === 'string') {
			args.connectId = connectId;
		} else {
			args.connectNode = connectId;
		}

		return clientControlsFactory.createControl('Aras.Client.Controls.Public.ToolBar', args, function(toolbar) {
			toolbarApplet = toolbar;

			var initData = [];
			self.initToolbarEvents(toolbarApplet, contextItem, contextParams);
			contextItem.toolbarApplet = toolbarApplet;
			contextItem.toolbarId = toolbarId;
			contextItem.items = items;
			contextItem.contextParams = contextParams;
			self.loadToolbarFromCommandBars(contextItem, initData);
			toolbarApplet.show();

			for (i = 0; i < items.length ; ++i) { // after toolbar.show()
				var currentItem = items[i];
				var controlId = currentItem.selectSingleNode('name');
				controlId = controlId ? controlId.text : null;
				var widget = toolbarApplet.GetItem(controlId);
				if (widget) {
					self.utils.applyAdditionalData(widget, initData[controlId], true);
				}
			}

			self.dispatchCommandBarLoadedEvent(locationName, toolbarApplet);

			return toolbar;
		}).catch(function(e) {
			aras.AlertError('createConfigurableToolbar: ' + e);
		});

	};

	CompatCuiToolbar.prototype._getOnKeyDownHandler = function(item) {
		var methodId = this.utils.getHandlerName(item, null, 'on_keydown_handler');
		var evalOnKeyDownHandler = function evalOnKeyDownHandler(methodParams) {
			this.utils.evalCommandBarItemMethod(methodId, methodParams);
		}.bind(this);

		return methodId ? evalOnKeyDownHandler : null;
	};

	CompatCuiToolbar.prototype._getToolbarsSplitByItemClassification = function(allItems, classification) {
		var toolbars = [];
		var initHandlers = this.utils.prepareInitHandlers(allItems);

		for (var i = 0; i < allItems.length ; i++) {
			var currentItem = allItems[i];
			var itemClassification = currentItem.selectSingleNode('item_classification').text;
			var type = currentItem.getAttribute('type');
			if (classification && itemClassification === classification) {
				itemClassification = '';
			}
			var name = currentItem.selectSingleNode('name').text;
			if (itemClassification) {
				name = name.replace(itemClassification + '_', '');
			} else {
				itemClassification = '$EmptyClassification';
			}

			var label = currentItem.selectSingleNode('label');
			label = label ? label.text : '';
			var tooltip = currentItem.selectSingleNode('tooltip_template');
			tooltip = tooltip ? tooltip.text : null;
			var initData = currentItem.selectSingleNode('additional_data');
			initData = initData ? initData.text : '';
			var image = currentItem.selectSingleNode('image');
			image = image ? image.text : '';
			var includeEvents = currentItem.selectSingleNode('include_events');
			includeEvents = includeEvents ? includeEvents.text : '';

			if (!label && type !== 'CommandBarEdit' && type !== 'CommandBarDropDown') {
				label = name;
			}
			var idx = currentItem.getAttribute('id'); //CommandBarButton id
			var toolbarItem = {
				idx: idx,
				type: type,
				name: name,
				label: aras.escapeXMLAttribute(label),
				tooltip: tooltip,
				onClickHandler: this.utils.getOnClickHandler(currentItem),
				onInitHandler: initHandlers[idx],
				includeEvents: includeEvents,
				onKeyDownHandler: this._getOnKeyDownHandler(currentItem),
				initData: initData,
				image: image
			};

			if (!toolbars[itemClassification]) {
				toolbars[itemClassification] = [];
			}

			toolbars[itemClassification].push(toolbarItem);
		}
		return toolbars;
	};

	CompatCuiToolbar.prototype.loadToolbarFromCommandBars = function(contextItem, initData) {
		this.private.loadToolbarImplementation(contextItem, initData, false);
	};

	CompatCuiToolbar.prototype.loadToolbarFromCommandBarsAsync = function(contextParams, initData) {
		return this.private.loadToolbarImplementation(contextParams, initData, true);
	};

	CompatCuiToolbar.prototype._loadToolbarFromCommandBars = function(contextItem, outInitData) {
		/// <returns>XML for toolbar</returns>
		if (this.utils.noItems(contextItem.items)) {
			return null;
		}

		if (!contextItem.toolbarApplet.handlersMap) {
			contextItem.toolbarApplet.handlersMap = [];
		}

		if (!contextItem.toolbarApplet.initHandlersMap) {
			contextItem.toolbarApplet.initHandlersMap = [];
		}

		var defaultOnClickHandler = contextItem.defaultOnClick ? function(inArgs) { return contextItem.defaultOnClick(inArgs.control); } : null;

		var itemClassification = '';
		if (contextItem['item_classification'] && contextItem['item_classification'] !== '%all_grouped_by_location%' &&
			contextItem['item_classification'] !== '%all_grouped_by_classification%') {
			itemClassification = contextItem['item_classification'];
		}

		var toolbars = this._getToolbarsSplitByItemClassification(contextItem.items, itemClassification);
		var toolbarsClassifications = Object.keys(toolbars);

		var xml =  '<toolbarapplet buttonstyle="windows" buttonsize="26,25">';
		for (var i = 0; i < toolbarsClassifications.length; i++) {
			var classification = toolbarsClassifications[i];
			var toolbarItems = toolbars[classification];
			var toolbarId = classification === '$EmptyClassification' && contextItem.toolbarId ? contextItem.toolbarId : classification;
			xml += this.utils.format('<toolbar id="{0}">', toolbarId);

			for (var j = 0; j < toolbarItems.length; j++) {
				var currentItem = toolbarItems[j];
				var initHandlerResult = undefined;
				if (currentItem.onInitHandler) {
					var itemTypeId = contextItem.itemType ? contextItem.itemType.getAttribute('id') : null;
					var inArgs = {itemType: contextItem.itemType, itemTypeId: itemTypeId, itemId: contextItem.itemID,
							item: contextItem.item, controlId: name, isReinit: false, contextParams: contextItem.contextParams, currentItem: currentItem};
					initHandlerResult = this.private.runOnInitHandler(currentItem.onInitHandler, null, inArgs);
				}

				if (initHandlerResult && initHandlerResult.hasOwnProperty('cui_visible') && !initHandlerResult['cui_visible']) {
					continue;
				}
				outInitData[currentItem.name] = this.utils._getCommandBarItemAdditionalData(currentItem.initData, initHandlerResult);
				var tooltip = currentItem.tooltip ? this._getTooltipFromTooltipTemplate(currentItem.tooltip) : '';

				var attributesMapping = {'image': currentItem.image, 'id': currentItem.name, 'tooltip': tooltip, 'idx': currentItem.idx};
				if (outInitData[currentItem.name]) {
					attributesMapping.disabled = outInitData[currentItem.name]['cui_disabled'];
					attributesMapping.invisible = outInitData[currentItem.name]['cui_invisible'];
					attributesMapping.style = outInitData[currentItem.name]['cui_style'];
					attributesMapping.class = outInitData[currentItem.name]['cui_class'];
					attributesMapping.placeholder = outInitData[currentItem.name]['cui_placeholder'];
					attributesMapping.type = outInitData[currentItem.name]['cui_type'];
					attributesMapping.right = outInitData[currentItem.name].right;
					attributesMapping.state = outInitData[currentItem.name].state;
					attributesMapping['label_position'] = outInitData[currentItem.name]['label_position'];
				}

				var initContext;
				var attributesAsString;
				switch (currentItem.type) {
					case 'CommandBarButton':
						attributesAsString = this.utils._mapExtraControlPropsToXml(attributesMapping);
						xml += this.utils.format('<button {0}>{1}</button>', attributesAsString, currentItem.label);

						contextItem.toolbarApplet.handlersMap[currentItem.idx] = currentItem.onClickHandler || defaultOnClickHandler;
						initContext = {events: currentItem.includeEvents, handler: currentItem.onInitHandler};
						contextItem.toolbarApplet.initHandlersMap[currentItem.idx] = initContext;
						break;
					case 'CommandBarDropDown':
						attributesMapping.label = currentItem.label;
						attributesAsString = this.utils._mapExtraControlPropsToXml(attributesMapping);
						xml += this.utils.format('<choice {0} >', attributesAsString);

						var dropDownItems = outInitData[currentItem.name];
						if (outInitData[currentItem.name] && outInitData[currentItem.name]['cui_items']) {
							dropDownItems = outInitData[currentItem.name]['cui_items'];
						}

						if (dropDownItems && dropDownItems.length) {
							for (var k = 0; k < dropDownItems.length; ++k) {
								dropDownItems[k].tooltip = tooltip;
								xml += this.utils.format('<choiceitem {0}>{1}</choiceitem>',
									this.utils._mapExtraControlPropsToXml(dropDownItems[k]),
									(dropDownItems[k].label || dropDownItems[k].name));
							}
						}
						xml += '</choice>';
						initContext = {events: currentItem.includeEvents, handler: currentItem.onInitHandler};
						contextItem.toolbarApplet.initHandlersMap[currentItem.idx] = initContext;
						break;
					case 'CommandBarSeparator':
						xml += '<separator/>';
						break;
					case 'CommandBarEdit':
						attributesMapping.label = currentItem.label;
						attributesAsString = this.utils._mapExtraControlPropsToXml(attributesMapping);
						xml += this.utils.format('<edit {0} />', attributesAsString);
						if (currentItem.onKeyDownHandler) {
							contextItem.toolbarApplet.handlersMap[currentItem.idx] = currentItem.onKeyDownHandler;
						}
						initContext = {events: currentItem.includeEvents, handler: currentItem.onInitHandler};
						contextItem.toolbarApplet.initHandlersMap[currentItem.idx] = initContext;
						break;
				}
			}
			xml += '</toolbar>';
		}
		xml += '</toolbarapplet>';

		return toolbarsClassifications.length > 0 ? xml : null;
	};

	CompatCuiToolbar.prototype.initToolbarEvents = function(toolbarApplet, contextItem, contextParams) {
		clientControlsFactory.on(toolbarApplet, {
			'onClick': function(button) {
				var idx = button['_item_Experimental'].idx;
				if (idx && this.handlersMap[idx]) {
					this.handlersMap[idx]({control: button, contextItem: contextItem, contextParams: contextParams});
				}
			},
			'onKeyDown': function(textBox, evt) {
				if (textBox['_item_Experimental'].type === 'button') {
					return;
				}
				var idx = textBox['_item_Experimental'].idx;
				if (idx && this.handlersMap[idx]) {
					this.handlersMap[idx]({control: textBox, event: evt, contextItem: contextItem, contextParams: contextParams});
				}
			}
		});
	};

	CompatCuiToolbar.prototype.getExistToolbarId = function(locationName, contextParams) {
		var hash;
		this.private.getExistToolbarIdImplementation(locationName, contextParams, false).then(function(res) {
			hash = res;
		});
		return hash;
	};

	CompatCuiToolbar.prototype.getExistToolbarIdAsync = function(locationName, contextParams) {
		return this.private.getExistToolbarIdImplementation(locationName, contextParams, true);
	};

	CompatCuiToolbar.prototype.callInitHandlersForToolbar = function(eventState, eventType) {
		var topWindow = aras.getMostTopWindowWithAras(window);
		var toolbarPromise;
		//Main Window toolbar
		const itemsGridToolbar = window.toolbar;

		if (itemsGridToolbar && itemsGridToolbar.getToolbarInstance && itemsGridToolbar.getToolbarInstance()) {
			toolbarPromise = Promise.resolve(itemsGridToolbar);
		} else if (topWindow.tearOffMenuController) {
			toolbarPromise = topWindow.tearOffMenuController.when('ToolbarInitialized');
		}

		if (toolbarPromise) {
			toolbarPromise.then(function(toolbar) {
				if (toolbar) {
					this.updateToolbarItems(toolbar, eventState, eventType);
				}
			}.bind(this));
		}
	};

	CompatCuiToolbar.prototype.updateToolbarItems = function(toolbar, eventState, eventType, skipCheckEvents, contextParams) {
		let buttons = toolbar.getButtons('$');
		buttons = buttons.split('$');
		const inArgs = {eventState: eventState, eventType: eventType, isReinit: true, contextParams: contextParams};
		for (let i = 0; i < buttons.length; i++) {
			const tbItem = toolbar.getItem(buttons[i]);
			if (tbItem) {
				let widget = tbItem['_item_Experimental'];
				const idx = widget.idx;
				if (idx && toolbar.initHandlersMap[idx] && toolbar.initHandlersMap[idx].handler) {
					const initContext = toolbar.initHandlersMap[idx];
					const events = initContext.events ? initContext.events.split(',') : null;
					if (skipCheckEvents || (events && events.indexOf(eventType) !== -1)) {
						let reinitData;
						const tabsObj = aras.getMostTopWindowWithAras().arasTabs;
						if (tabsObj) {
							const frameElement = window.frameElement;
							const currentSelectedTab = tabsObj.selectedTab;
							tabsObj.selectedTab = frameElement ? frameElement.id : currentSelectedTab;

							reinitData = this.private.runOnInitHandler(initContext.handler, tbItem, inArgs);
							tabsObj.selectedTab = currentSelectedTab;
						} else {
							reinitData = this.private.runOnInitHandler(initContext.handler, tbItem, inArgs);
						}
						if (!reinitData) {
							continue;
						}
						if (tbItem._widget) {
							widget = tbItem._widget;
						}

						if (reinitData['cui_disabled'] !== undefined) {
							tbItem.setEnabled(!reinitData['cui_disabled']);
						}
						delete reinitData['cui_disabled'];

						if (reinitData['cui_class']) {
							widget.domNode.classList.add(reinitData['cui_class']);
							delete reinitData['cui_class'];
						}

						if (reinitData['cui_style']) {
							widget.set('style', widget.get('style') + '; ' + reinitData['cui_style']);
							delete reinitData['cui_style'];
						}

						if (reinitData['cui_placeholder']) {
							widget.setPlaceholder(reinitData['cui_placeholder']);
							delete reinitData['cui_placeholder'];
						}

						const keys = Object.keys(reinitData);
						for (let j = 0; j < keys.length; j++) {
							const key = keys[i];
							widget.set(key, reinitData[key]);
						}
					}
				}
			}
		}
	};

	return CompatCuiToolbar;
})();

/** ..\Modules\aras.innovator.CUI\Scripts\Classes\ConfigurableUI.js **/
function ConfigurableUI(Utils, CuiDataLoader, CompatCuiToolbar, CuiShortcuts, CuiContextMenu, CuiMenu, CuiSidebar, CuiTooltip) {

	function ConfigurableUI() {
		this.dataLoader = new CuiDataLoader();
		this.utils = new Utils();
		var self = this;
		this.private = {
			declare: function(fieldName, func) {
				var boundFunc = func.bind(self);
				this[fieldName] = boundFunc;
			}
		};
		if (this.super && this.super.length > 0) {
			for (var i = 0; i < this.super.length; i++) {
				var superClass = this.super[i];
				if (superClass.constructor) {
					superClass.constructor.call(this);
				}
			}
		}
	}

	ConfigurableUI.prototype.callInitHandlers = function(eventType) {
		var eventState = {};
		this.callInitHandlersForToolbar(eventState, eventType);
		this.callInitHandlersForMenu(eventState, eventType);
	};

	ConfigurableUI.prototype.super = [];
	function inherit(child, parents) {
		for (var i = 0; i < parents.length; i++) {
			var F = function() {};
			F.prototype = parents[i].prototype;
			var f = new F();
			for (var prop in child.prototype) {
				f[prop] = child.prototype[prop];
			}
			child.prototype = f;
			child.prototype.super.push(parents[i].prototype);
		}
	}

	inherit(ConfigurableUI, [CompatCuiToolbar, CuiShortcuts, CuiContextMenu, CuiMenu, CuiSidebar, CuiTooltip]);
	return ConfigurableUI;
}
window.CUI_ConfigurableUI = ConfigurableUI(CuiUtils, CuiDataLoader, CompatCuiToolbar, CuiShortcuts, CuiContextMenu, CuiMenu, CuiSidebar, CuiTooltip);

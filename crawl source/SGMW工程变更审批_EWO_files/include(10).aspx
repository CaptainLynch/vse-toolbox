
/** Dependencies.js **/
function Dependencies() { }

Dependencies.view = function DependenciesView(itemTypeName, itemId, viewWhereUsed, aras, isInTearOff) {
	let params = '';
	const itemType = aras.getItemTypeDictionary(itemTypeName, 'name');
	if (!itemType || itemType.isError()) {
		return;
	}

	const item = aras.getItemById(itemTypeName, itemId, 0);
	if (!item) {
		return;
	}

	if (aras.isNew(item)) {
		aras.AlertError(aras.getResource('', 'dependencies.is_new_error', itemType.getProperty('label')));
		return;
	}

	let url = aras.getScriptsURL();
	let strBrItemID;

	if (viewWhereUsed) {
		url += 'whereUsed.html?id=' + itemId + '&type_name=' + itemTypeName;
		strBrItemID = itemId + '_whereUsed';
	} else {
		url += 'StructureBrowser.html?id=' + itemId + '&type_name=' + itemTypeName;
		strBrItemID = itemId + '_StructureBrowser';
	}

	const wndWidth = screen.width * 0.7;
	const wndHeight = screen.height * 0.7;
	const leftCoord = screen.width / 2 - wndWidth / 2;
	const topCoord = screen.height / 2 - wndHeight / 2;
	params = 'left=' + leftCoord + ', top=' + topCoord + ', width=' + wndWidth + ', height=' +
	wndHeight + ', menubar=0, resizable=1, scrollbars=0, location=0, toolbar=0, status=0' + (isInTearOff ? ', isOpenInTearOff=true' : '');

	let win = aras.uiFindWindowEx(strBrItemID);
	if (!win || aras.isWindowClosed(win)) {
		win = aras.uiOpenWindowEx(strBrItemID, params);
		if (!win) {
			return;
		}

		aras.uiRegWindowEx(strBrItemID, win);
		window.open(url, win.name, params);
	} else {
		win.focus();
	}
};

/** ItemsGrid\BaseItemTypeGrid.js **/
/*
Used by MainGridFactory.js
*/

function BaseItemTypeGrid() {
	var topWindow = aras.getMostTopWindowWithAras(window);
	this.cui = topWindow.cui;
}

BaseItemTypeGrid.prototype.onInitialize = function BaseItemTypeGrid_onInitialize() {
	if (!this.cui) {
		var topWindow = aras.getMostTopWindowWithAras(window);
		this.cui = topWindow.cui;
	}

	currItemType = aras.getItemTypeDictionary(aras.getItemTypeName(itemTypeID));
	if (!currItemType || currItemType.isError()) {
		currItemType = null;
		return false;
	}

	currItemType = currItemType.node;
	varName_queryDate = 'IT_' + itemTypeID + '_queryDate';
	visiblePropNds = [];

	xml_ready_flag = false;

	if(aras.getLanguageDirection() === 'rtl') {
		document.documentElement.dir = 'rtl';
	}

	itemTypeName = aras.getItemProperty(currItemType, 'name');
	itemTypeLabel = aras.getItemProperty(currItemType, 'label');
	if (!itemTypeLabel) {
		itemTypeLabel = itemTypeName;
	}

	isVersionableIT = (aras.getItemProperty(currItemType, 'is_versionable') == '1');
	showReleaseEffectiveDateRows(isVersionableIT);
	use_src_accessIT = (aras.getItemProperty(currItemType, 'use_src_access') == '1');
	isManualyVersionableIT = (isVersionableIT && aras.getItemProperty(currItemType, 'manual_versioning') == '1');
	isRelationshipIT = (aras.getItemProperty(currItemType, 'is_relationship') == '1');
	can_addFlg = aras.getPermissions('can_add', itemTypeID);

	visiblePropNds = aras.getvisiblePropsForItemType(currItemType);
	aras.uiInitItemsGridSetups(currItemType, visiblePropNds);

	var gridSetups = aras.sGridsSetups[itemTypeName];
	if (!(gridSetups)) {
		return false;
	}

	gridSetups.query = aras.newQryItem(itemTypeName);
	currQryItem = gridSetups.query;
	currQryItem.setPage(1);
	currQryItem.removeAllCriterias();
	this.initMenuVariables();

	return true;
};

BaseItemTypeGrid.prototype.initMenuVariables = function BaseItemTypeGrid_initMenuVariables() {
	popupMenuState = {};
	this.popupMenuStateChanged = false;
};

BaseItemTypeGrid.prototype.onLockCommand = function BaseItemTypeGrid_onLockCommand(ignorePolymophicWarning, itemIds) {
	itemIds = itemIds || grid.getSelectedItemIds();

	if (!itemIds.length) {
		aras.AlertError(aras.getResource('', 'itemsgrid.select_item_type_first', itemTypeLabel));
		return false;
	}

	var realItemTypeNames = getRealItemTypeNames(itemIds),
		realItemTypeName, itemId, i;

	for (i = 0; i < itemIds.length; i++) {
		itemId = itemIds[i];

		if (!execInTearOffWin(itemId, 'lock')) {
			realItemTypeName = realItemTypeNames[itemId];

			if (realItemTypeName) {
				focus();

				if (aras.lockItem(itemId, realItemTypeName)) {
					var itemNode = aras.getItemById('', itemId, 0);

					if (itemNode) {
						if (updateRowSearchGrids(itemNode) === false) {
							return;
						}
					}
				}
			}
		}
	}

	onSelectItem(itemIds[0]);
};

BaseItemTypeGrid.prototype.updateItem = function BaseItemTypeGrid_updateItem(oldItem, newItem) {
	var qry = currQryItem.getResult();
	if (qry) {
		var type = oldItem.getAttribute('type');
		var typeId = oldItem.getAttribute('typeId');
		var id = oldItem.getAttribute('id');
		var typeCondition = '@type=\'' + type + '\'', i;

		var polyItems = aras.getPolymorphicsWhereUsedAsPolySource(typeId);
		if (polyItems.length > 0) {
			for (i = 0; i < polyItems.length; i++) {
				var polyItem = polyItems[i];
				typeCondition += ' or @type=\'' + polyItem.name + '\'';
			}
		}
		var nodes = qry.selectNodes('./Item/*[(' + typeCondition + ') and text()=\'' + id + '\']');

		for (i = 0; i < nodes.length; i++) {
			var node = nodes[i];
			var idNode = node.parentNode.getAttribute('id');
			var indexColumn = grid.getColumnIndex(node.nodeName + '_D');
			if (idNode && indexColumn > -1) {
				var cell = grid.cells(idNode, indexColumn);
				if (aras.getItemProperty(newItem, 'keyed_name') !== aras.getItemProperty(oldItem, 'keyed_name')) {
					node.setAttribute('keyed_name', aras.getItemProperty(newItem, 'keyed_name'));
					cell.setValue(aras.getItemProperty(newItem, 'keyed_name'));
				}

				if (oldItem.getAttribute('id') !== newItem.getAttribute('id')) {
					node.text = newItem.getAttribute('id');
					cell.setValue(aras.getItemProperty(newItem, 'keyed_name'));
					cell.setLink('\'' + type + '\',\'' + newItem.getAttribute('id') + '\'');
				}
			}
		}
	}
};

BaseItemTypeGrid.prototype.onUnlockCommand = function BaseItemTypeGrid_onUnlockCommand(ignorePolymophicWarning, itemIds) {
	itemIds = itemIds || grid.getSelectedItemIds();

	if (!itemIds.length) {
		aras.AlertError(aras.getResource('', 'itemsgrid.select_item_type_first', itemTypeLabel));
		return false;
	}

	var realItemTypeNames = getRealItemTypeNames(itemIds),
		unlockedItem, itemNode,
		realItemTypeName, itemId, i;
	var dlgPromise = Promise.resolve();
	var topWin = aras.getMostTopWindowWithAras(window);
	var dialogParams = {
		additionalButton: {
			text: aras.getResource('', 'common.discard'),
			actionName: 'discard'
		},
		buttonOkText: aras.getResource('', 'common.save'),
		title: aras.getResource('', 'item_methods_ex.unsaved_changes')
	};
	var unlockItem = function(itemNode, saveChanges) {
		unlockedItem = aras.unlockItemEx(itemNode, saveChanges);

		if (!unlockedItem) {
			return;
		}
		if (itemNode && unlockedItem.getAttribute('id') != itemNode.getAttribute('id')) {
			deleteRowSearchGrids(itemNode);
		}
		itemNode = unlockedItem;
		if (itemNode) {
			updateRowSearchGrids(itemNode);
		}
	};
	var processItem = function(itemNode, realItemTypeName) {
		var isDirty = aras.isDirtyEx(itemNode);

		if (isDirty) {
			const dialogMessage = aras.getResource('', 'item_methods_ex.changes_not_saved');
			return topWin.ArasModules.Dialog.confirm(dialogMessage, dialogParams).then(function(res) {
				if (!res || res === 'cancel') {
					return;
				}
				unlockItem(itemNode, res === 'ok');
			});
		} else {
			unlockItem(itemNode, false);
		}
	};

	for (i = 0; i < itemIds.length; i++) {
		itemId = itemIds[i];

		if (!execInTearOffWin(itemId, 'unlock')) {
			realItemTypeName = realItemTypeNames[itemId];

			if (realItemTypeName) {
				itemNode = aras.getFromCache(itemId);
				focus();

				if (!itemNode) {
					itemNode = aras.unlockItem(itemId, realItemTypeName);
					if (itemNode && updateRowSearchGrids(itemNode) === false) {
						return;
					}
				} else {
					dlgPromise = dlgPromise.then(processItem.bind(this, itemNode, realItemTypeName));
				}
			}
		}
	}

	dlgPromise.then(function() {
		onSelectItem(itemIds[0]);
	});
};

BaseItemTypeGrid.prototype.isUnusedAction = function BaseItemTypeGrid_isUnusedAction(action) {
	return false;
};

BaseItemTypeGrid.prototype.showError = function BaseItemTypeGrid_showError(error) {
	if (error) {
		aras.AlertError(error);
	}
	return !!error;
};

BaseItemTypeGrid.prototype.onLink = function BaseItemTypeGrid_onLink(typeName, id, altMode) {
	var itemType = aras.getItemTypeDictionary(typeName, 'name');
	if (itemType && !itemType.isError() && aras.isPolymorphic(itemType.node)) {
		var item = aras.getItemById(typeName, id, 0);
		if (item.getAttribute('type') === typeName) {
			var polyTypeId = aras.getItemProperty(item, 'itemtype');
			typeName = aras.getItemTypeName(polyTypeId);
			aras.removeFromCache(item);
		}
	}
	aras.uiShowItem(typeName, id, null, altMode);
};

BaseItemTypeGrid.prototype.getMenuContext = function(commandId, rowId, col) {
	return {
		commandId: commandId, rowId: rowId, col: col, currQryItem: currQryItem, itemType: currItemType, selectedItemIds: grid.getSelectedItemIds(),
		gridInstance: this,
		menuType: this.constructor.name || this.constructor.toString().match(/function\s*([^(]*)\(/)[1]
	};
};

BaseItemTypeGrid.prototype.fillPopupMenu = function BaseItemTypeGrid_fillContextMenu(rowId, col) {
	var popupMenu = grid.getMenu();
	if (popupMenuStateChanged || popupMenu.getItemCount() === 0) {
		popupMenu.removeAll();
		popupMenuStateChanged = false;
		this.cui.fillPopupMenu("PopupMenuItemGrid", popupMenu, this.getMenuContext(null, rowId, col), popupMenuState);
	}
};

BaseItemTypeGrid.prototype.onHeaderMenuClicked = function(commandId, rowsId, col) {
	switch (commandId) {
		case "hideCol":
			hideColumn(col);
			var columnSelectionBlock = document.getElementById('column_select_block');
			if (!columnSelectionBlock.classList.contains('hidden')) {
				var column = columnSelectionControl.columns[col];
				if (!column.hidden) {
					columnSelectionControl.toggleRowSelection(column.propertyId, true);
				}
			}
			break;
		case "insertCol":
			showColumn(col);
			break;
	}
};

// ================= Handlers for Actions AddItemsForChange (In Documents & Parts) =============================
function handlerForAddItemsForChange(cmdID) {
	var arasObj = aras;
	var itemIDs = grid.getSelectedItemIDs();

	var arr = cmdID.split(':');
	var act = arasObj.getItemFromServer('Action', arr[1], 'name,method(name,method_type,method_code),type,target,location,body,on_complete(name,method_type,method_code),item_query');
	if (!act) {
		return;
	}


	var countStartDefaultAction = 0;
	function startDefaultAction() {
		countStartDefaultAction++;
		if (countStartDefaultAction == itemIDs.length) {
			//Start Action for last select Document(or Part). And Action show form for all selected Documents(or Parts)
			arasObj.invokeAction(act.node, arr[2], itemIDs[itemIDs.length - 1]);
		}
	}

	for (var i = 0; i < itemIDs.length; i++) {
		var itemID = itemIDs[i];
		var tempItem =aras.itemsCache.getItemByXPath('//Item[@id=\'' + itemID + '\' and (@isDirty=\'1\' or @isTemp=\'1\')]');

		if (tempItem) {
			if (arasObj.confirm(arasObj.getResource('plm', 'changeitem.saveit'))) {
				arasObj.saveItemExAsync(tempItem).then(startDefaultAction);
			}
		} else {
			startDefaultAction();
		}
	}
}

//For Documents
window['onAction:83FB72FC3E4D42B8B51BCD7F4194E527:B88C14B99EF449828C5D926E39EE8B89Command'] = handlerForAddItemsForChange;
//For Parts
window['onAction:83FB72FC3E4D42B8B51BCD7F4194E527:4F1AC04A2B484F3ABA4E20DB63808A88Command'] = handlerForAddItemsForChange;
//For Cad
window['onAction:83FB72FC3E4D42B8B51BCD7F4194E527:CCF205347C814DD1AF056875E0A880ACCommand'] = handlerForAddItemsForChange;
// ================= Handlers for AddItemsForChange (In Documents & Parts) =============================

/** ItemsGrid\ItemGrid.js **/
/*
Used by MainGridFactory.js
*/

function ItemGrid() {
	ItemGrid.superclass.constructor();
}

inherit(ItemGrid, BaseItemTypeGrid);

ItemGrid.prototype.setMenuState = function ItemGrid_setMenuState(rowId, col) {
	if (currQryItem) {
		var queryItem = currQryItem.getResult(),
			itemNd = queryItem.selectSingleNode('Item[@id="' + rowId + '"]') || aras.getFromCache(rowId),
			brokenFlg = !Boolean(itemNd),
			itemIDs, itemIdsCount;

		var keys = Object.keys(popupMenuState);
		if (keys.length === 0) {
			popupMenuState['com.aras.innovator.cui_default.pmig_Save As'] = false;
			popupMenuState['com.aras.innovator.cui_default.pmig_View'] = false; //4
			popupMenuState['com.aras.innovator.cui_default.pmig_separator1'] = false;
			popupMenuState['com.aras.innovator.cui_default.pmig_Purge'] = false; //7
			popupMenuState['com.aras.innovator.cui_default.pmig_Delete'] = false; //8
			popupMenuState['com.aras.innovator.cui_default.pmig_separator2'] = false;
			popupMenuState['com.aras.innovator.cui_default.pmig_Lock'] = false; //10
			popupMenuState['com.aras.innovator.cui_default.pmig_Unlock'] = false; //11
			popupMenuState['com.aras.innovator.cui_default.pmig_Version'] = false;
			popupMenuState['com.aras.innovator.cui_default.pmig_Revisions'] = false;
			popupMenuState['com.aras.innovator.cui_default.pmig_Promote'] = false;
			popupMenuState['com.aras.innovator.cui_default.pmig_Where Used'] = false;
			popupMenuState['com.aras.innovator.cui_default.pmig_Structure Browser'] = false;
			popupMenuState['com.aras.innovator.cui_default.pmig_Properties'] = false;
			popupMenuState['com.aras.innovator.cui_default.pmig_Add to Desktop'] = false;
			popupMenuStateChanged = true;
		}

		if (!brokenFlg && currItemType) {
			itemIDs = grid.getSelectedItemIds();
			itemIdsCount = itemIDs.length;

			var itemID = rowId;
			var locked_by = aras.getItemProperty(itemNd, 'locked_by_id');
			var isTemp = aras.isTempEx(itemNd);
			var isDirty = aras.isDirtyEx(itemNd);

			var discoverOnlyFlg = (itemNd && itemNd.getAttribute('discover_only') == '1');
			var editFlg = ((isTemp || locked_by == userID) && !discoverOnlyFlg);
			var saveFlg = (editFlg && (aras.getFromCache(itemID) != null));
			var viewFlg = (itemIdsCount == 1 && !discoverOnlyFlg);
			var purgeFlg = (isTemp || (locked_by == ''));
			var lockFlg = aras.uiItemCanBeLockedByUser(itemNd, isRelationshipIT, use_src_accessIT);
			var unlockFlg = (locked_by == userID || (!isTemp && locked_by != '' && aras.isAdminUser()));
			var copyFlg = (itemIdsCount == 1 && !isTemp && can_addFlg);
			var singlePromoteFlg = (locked_by == '' && !isTemp) && (itemIdsCount == 1);
			var massPromoteFlg = itemIdsCount > 1 && !aras.isPolymorphic(currItemType);
			var add2desktopFlg = !isTemp;

			var copy2clipboardFlg = aras.getItemProperty(currItemType, 'is_relationship') == '1' && aras.getItemProperty(currItemType, 'is_dependent') != '1' && (!isFunctionDisabled(itemTypeName, 'Copy'));
			var pasteFlg = !aras.clipboard.isEmpty() && (isTemp || (locked_by == userID)) && (!isFunctionDisabled(itemTypeName, 'Paste'));
			var pasteSpecialFlg = !aras.clipboard.isEmpty() && (isTemp || (locked_by == userID)) && (!isFunctionDisabled(itemTypeName, 'Paste Special'));
			var showClipboardFlg = !aras.clipboard.isEmpty();
			var addItem2PackageFlg = ((itemID == '' || isTemp) ? false : true);

			if (itemIdsCount > 1) {
				var idsArray = [],
					itemNds, tmpItemNd,
					i;

				for (i = 0; i < itemIdsCount; i++) {
					idsArray.push('@id=\'' + itemIDs[i] + '\'');
				}

				itemNds = queryItem.selectNodes('Item[' + idsArray.join(' or ') + ']');
				for (i = 0; i < itemNds.length; i++) {
					tmpItemNd = itemNds[i];
					itemID = aras.getItemProperty(tmpItemNd, 'id');

					if (!tmpItemNd) {
						brokenFlg = true;
						break;
					}

					locked_by = aras.getItemProperty(tmpItemNd, 'locked_by_id');
					isTemp = aras.isTempEx(tmpItemNd);
					isDirty = aras.isDirtyEx(tmpItemNd);

					editFlg = editFlg && (isTemp || (locked_by == userID));
					saveFlg = saveFlg && (editFlg && aras.getFromCache(itemID));
					purgeFlg = purgeFlg && (isTemp || (locked_by == ''));
					lockFlg = lockFlg && aras.uiItemCanBeLockedByUser(tmpItemNd, isRelationshipIT, use_src_accessIT);

					unlockFlg = unlockFlg && (locked_by == userID || (!isTemp && locked_by != '' && aras.isAdminUser()));
					add2desktopFlg = add2desktopFlg & !isTemp;
					pasteFlg = pasteFlg && !aras.clipboard.isEmpty() && (isTemp || (locked_by == userID));
					pasteSpecialFlg = pasteSpecialFlg && !aras.clipboard.isEmpty() && (isTemp || (locked_by == userID));
					addItem2PackageFlg = ((itemID == '' || isTemp) ? false : true);
				}

				if (pasteFlg) {
					pasteFlg = aras.isLCNCompatibleWithIT(itemTypeID);
				}
			}
		}

		if (!brokenFlg) {
			var newPopupMenuState = [];
			newPopupMenuState['com.aras.innovator.cui_default.pmig_Save As'] = (!(isFunctionDisabled(itemTypeName, 'Save As')) && copyFlg);
			newPopupMenuState['com.aras.innovator.cui_default.pmig_View'] = viewFlg && !isFunctionDisabled(itemTypeName, 'View');
			newPopupMenuState['com.aras.innovator.cui_default.pmig_Purge'] = (purgeFlg && isVersionableIT);
			newPopupMenuState['com.aras.innovator.cui_default.pmig_Delete'] = purgeFlg && !isFunctionDisabled(itemTypeName, 'Delete'); //delete is always available, but purge is only for versioanble
			newPopupMenuState['com.aras.innovator.cui_default.pmig_Lock'] = lockFlg && !isFunctionDisabled(itemTypeName, 'Lock');
			newPopupMenuState['com.aras.innovator.cui_default.pmig_Unlock'] = unlockFlg && !isFunctionDisabled(itemTypeName, 'Unlock');
			newPopupMenuState['com.aras.innovator.cui_default.pmig_Version'] = (!(isFunctionDisabled(itemTypeName, 'Version')) && isManualyVersionableIT && itemIDs && itemIdsCount == 1 && !isTemp && (locked_by == userID || locked_by == ''));
			newPopupMenuState['com.aras.innovator.cui_default.pmig_Revisions'] = (isVersionableIT && !isTemp && itemIDs && itemIdsCount == 1);
			newPopupMenuState['com.aras.innovator.cui_default.pmig_Promote'] = ((singlePromoteFlg || massPromoteFlg) && !(isFunctionDisabled(itemTypeName, 'Promote')));
			newPopupMenuState['com.aras.innovator.cui_default.pmig_Where Used'] = (itemIDs && itemIdsCount == 1);
			newPopupMenuState['com.aras.innovator.cui_default.pmig_Structure Browser'] = (itemIDs && itemIdsCount == 1);
			newPopupMenuState['com.aras.innovator.cui_default.pmig_Properties'] = (itemIDs && itemIdsCount == 1);
			newPopupMenuState['com.aras.innovator.cui_default.pmig_Add to Desktop'] = add2desktopFlg;
			newPopupMenuState['com.aras.innovator.cui_default.pmig_separator1'] = true;
			newPopupMenuState['com.aras.innovator.cui_default.pmig_separator2'] = true;

			const keys = Object.keys(newPopupMenuState);
			keys.forEach(function(key) {
				const value = newPopupMenuState[key];
				if (popupMenuState[key] !== value) {
					popupMenuStateChanged = true;
					popupMenuState[key] = value;
				}
			});
		}
	}
};

ItemGrid.prototype.onLockCommand = function ItemGrid_onLockCommand(ignorePolymophicWarning, itemIDs) {
	if (!ignorePolymophicWarning && aras.isPolymorphic(currItemType)) {
		aras.AlertError(aras.getResource('', 'itemsgrid.poly_item_cannot_be_locked_from_location'));
		return false;
	}
	return ItemGrid.superclass.onLockCommand();
};

ItemGrid.prototype.onUnlockCommand = function ItemGrid_onUnlockCommand(ignorePolymophicWarning, itemIDs) {
	if (!ignorePolymophicWarning && aras.isPolymorphic(currItemType)) {
		aras.AlertError(aras.getResource('', 'itemsgrid.poly_item_cannot_be_unlocked_from_location'));
		return false;
	}
	return ItemGrid.superclass.onUnlockCommand();
};

ItemGrid.prototype.onEditCommand = function ItemGrid_onEditCommand(itemId) {
	if (aras.isPolymorphic(currItemType)) {
		aras.AlertError(aras.getResource('', 'itemsgrid.polyitem_cannot_be_edited_from_the_location'));
		return false;
	}

	if (!itemId) {
		aras.AlertError(aras.getResource('', 'itemsgrid.select_item_type_first', itemTypeLabel));
		return false;
	}

	if (execInTearOffWin(itemId, 'edit')) {
		return true;
	}

	if (itemTypeName === 'SelfServiceReport') {
		var existingWnd = aras.uiFindAndSetFocusWindowEx(aras.SsrEditorWindowId);
		if (existingWnd) {
			return existingWnd.showMultipleReportsError(itemId);
		}
	}

	var itemNode = aras.getItemById(itemTypeName, itemId, 0, undefined, '*'),
		notLocked;

	if (!itemNode) {
		if (itemTypeName == 'Form') {
			itemNode = aras.getItemFromServer(itemTypeName, itemId, 'locked_by_id').node;
		}

		if (!itemNode) {
			aras.AlertError(aras.getResource('', 'itemsgrid.failed2get_itemtype', itemTypeLabel));
			return false;
		}
	}

	notLocked = (!aras.isTempEx(itemNode) && aras.getItemProperty(itemNode, 'locked_by_id') == '');
	if (notLocked) {
		if (!aras.lockItemEx(itemNode)) {
			return false;
		}

		itemNode = aras.getItemById(itemTypeName, itemId, 0);
		if (updateRowSearchGrids(itemNode) !== false) {
			onSelectItem(itemId);
		}
	}

	aras.uiShowItemEx(itemNode, aras.getPreferenceItemProperty('Core_GlobalLayout', null, 'core_view_mode'));
};

ItemGrid.prototype.onDoubleClick = function ItemGrid_onDoubleClick(itemId, altMode) {
	if (popupMenuState['com.aras.innovator.cui_default.pmig_View'] || !isFunctionDisabled(itemTypeName, 'DoubleClick')) {
		aras.uiShowItem(itemTypeName, itemId, null, altMode);
	}
};

ItemGrid.prototype.onClick = function ItemGrid_onClick(itemId) {
	previewPane.showFormByItemId(itemId, itemTypeName);
};

ItemGrid.prototype.onMenuClicked = function ItemGrid_onMenuClicked(commandId, rowId, col) {
	switch (commandId) {
		case 'locked_criteria:clear':
			grid.setCellValue('input_row', 0, '<img src=\'\'>');
			break;
		case 'locked_criteria:by_me':
			grid.setCellValue('input_row', 0, '<img src=\'../images/ClaimOn.svg\'>');
			break;
		case 'locked_criteria:by_others':
			grid.setCellValue('input_row', 0, '<img src=\'../images/ClaimOther.svg\'>');
			break;
		case 'locked_criteria:by_anyone':
			grid.setCellValue('input_row', 0, '<img src=\'../images/ClaimAnyone.svg\'>');
			break;
		default:
			break;
	}

	return commandId;
};

ItemGrid.prototype.onMassPromote = function ItemGrid_onMassPromote(itemIds) {
	if (typeof itemIds === 'undefined' || itemIds === null) {
		return;
	}

	var newItemNd = aras.newItem('mpo_MassPromotion');
	aras.itemsCache.addItem(newItemNd);

	aras.setItemProperty(newItemNd, 'promote_type', window.itemTypeName);
	var relationships = newItemNd.ownerDocument.createElement('Relationships');
	var queryItems = currQryItem.getResult();

	for (var i = 0; i < itemIds.length; i++)
	{
		var selectedItem = aras.getFromCache(itemIds[i]);
		if (!selectedItem) {
			var itemId = itemIds[i];
			var query = 'Item[@id="' + itemId + '"]';
			selectedItem = queryItems.selectSingleNode(query);
		}
		if (selectedItem) {
			var cloned = selectedItem.cloneNode(true);
			relationships.appendChild(cloned);
		}
	}
	newItemNd.appendChild(relationships);

	aras.uiShowItemEx(newItemNd, 'new');
};


/** ItemsGrid\InBasketTaskGrid.js **/
/*
Used by MainGridFactory.js
*/

function InBasketTaskGrid() {
	InBasketTaskGrid.superclass.constructor();
	var properties = ['created_by_id', 'created_on', 'modified_by_id', 'modified_on', 'locked_by_id',
		'major_rev', 'release_date', 'effective_date', 'generation', 'state'];
	this.propertiesHelper = {
		properties: properties.map(function(propertyId) {
			return {
				id: propertyId,
				label: aras.getResource('', 'item_info_table.' + (propertyId !== 'locked_by_id' ? propertyId : 'claimed_by_id') + '_txt')
			};
		}),
		showHeader: true,
		showThumbnails: true
	};
}

inherit(InBasketTaskGrid, BaseItemTypeGrid);

InBasketTaskGrid.prototype.setMenuState = function InBasketTaskGridSetMenuState(rowId, col) {
	if (!currQryItem) {
		return;
	}
	var res = currQryItem.getResult();
	var itemNd = res.selectSingleNode('Item[@id="' + rowId + '"]');
	if (!itemNd) {
		itemNd = arasObj.getFromCache(rowId);
	}

	var brokenFlg = !Boolean(itemNd);
	itemTypeName = aras.getItemTypeName(aras.getItemProperty(itemNd, 'itemtype'));

	var prefix = 'com.aras.innovator.cui_default.pmig_';
	var keys = Object.keys(popupMenuState);
	var i;
	var itemIDs;
	var discoverOnlyFlg;
	var lockFlg;
	var unlockFlg;

	if (keys.length === 0) {
		popupMenuState[prefix + 'separator1'] = true;
		popupMenuState[prefix + 'Lock'] = false;
		popupMenuState[prefix + 'Unlock'] = false;
		popupMenuState[prefix + 'separator2'] = true;
		popupMenuState[prefix + 'separator3'] = true;

		// disabled actions
		popupMenuState[prefix + 'Save As'] = false;
		popupMenuState[prefix + 'View'] = false;
		popupMenuState[prefix + 'Purge'] = false;
		popupMenuState[prefix + 'Delete'] = false;
		popupMenuState[prefix + 'Version'] = false;
		popupMenuState[prefix + 'Revisions'] = false;
		popupMenuState[prefix + 'Promote'] = false;
		popupMenuState[prefix + 'Where Used'] = false;
		popupMenuState[prefix + 'Structure Browser'] = false;
		popupMenuState[prefix + 'Properties'] = false;
		popupMenuState[prefix + 'Add to Desktop'] = false;
	}

	if (!brokenFlg && currItemType) {
		itemIDs = grid.getSelectedItemIds();
		var lockedBy = arasObj.getItemProperty(itemNd, 'locked_by_id');
		var isTemp = arasObj.isTempEx(itemNd);

		discoverOnlyFlg = (itemNd && itemNd.getAttribute('discover_only') == '1');
		var editFlg = ((isTemp || lockedBy == userID) && !discoverOnlyFlg);
		lockFlg = arasObj.uiItemCanBeLockedByUser(itemNd, isRelationshipIT, window['use_src_accessIT']) &&
			(arasObj.getItemProperty(itemNd, 'my_assignment') === '1');
		if (itemTypeName === 'Workflow Task') {
			lockFlg = lockFlg && (arasObj.getItemProperty(itemNd, 'status').toLowerCase() === 'active');
		}
		unlockFlg = (lockedBy == userID || (!isTemp && lockedBy !== '' && arasObj.isAdminUser()));

		if (itemIDs.length > 1) {
			var idsArray = itemIDs.map(function(value) {
				return '@id=\'' + value + '\'';
			});

			var itemNds = res.selectNodes('Item[' + idsArray.join(' or ') + ']');
			var currItemTypeName;
			for (i = 0; i < itemNds.length; i++) {
				itemNd = itemNds[i];
				itemID = arasObj.getItemProperty(itemNd, 'id');
				if (!itemNd) {
					brokenFlg = true;
					break;
				}

				currItemTypeName = itemTypeName;
				itemTypeName = aras.getItemTypeName(aras.getItemProperty(itemNd, 'itemtype'));

				ItemIsLocked = arasObj.isLocked(itemNd);

				lockedBy = arasObj.getItemProperty(itemNd, 'locked_by_id');
				isTemp = arasObj.isTempEx(itemNd);
				isDirty = arasObj.isDirtyEx(itemNd);

				editFlg = editFlg && (isTemp || (lockedBy == userID));
				lockFlg = lockFlg && arasObj.uiItemCanBeLockedByUser(itemNd, isRelationshipIT, window['use_src_accessIT']) &&
					(arasObj.getItemProperty(itemNd, 'my_assignment') === '1') && !isFunctionDisabled(itemTypeName, 'Lock');
				if (itemTypeName === 'Workflow Task') {
					lockFlg = lockFlg && (arasObj.getItemProperty(itemNd, 'status').toLowerCase() === 'active');
				}

				unlockFlg = unlockFlg && (lockedBy == userID || (!isTemp && lockedBy !== '' && arasObj.isAdminUser())) && !isFunctionDisabled(itemTypeName, 'Unlock');
			}
			itemTypeName = currItemTypeName;
		}
	}

	if (!brokenFlg && currQryItem) {
		var newPopupMenuState = [];
		newPopupMenuState[prefix + 'Lock'] = lockFlg && !isFunctionDisabled(itemTypeName, 'Lock');
		newPopupMenuState[prefix + 'Unlock'] = unlockFlg && !isFunctionDisabled(itemTypeName, 'Unlock');
		newPopupMenuState[prefix + 'separator2'] = popupMenuState[prefix + 'Lock'] || popupMenuState[prefix + 'Unlock'];
		newPopupMenuState[prefix + 'Version'] = false;
		newPopupMenuState[prefix + 'Revisions'] = false;
		newPopupMenuState[prefix + 'Where Used'] = false;
		newPopupMenuState[prefix + 'Structure Browser'] = false;
		newPopupMenuState[prefix + 'Properties'] = false;
		newPopupMenuState[prefix + 'Add to Desktop'] = false;

		keys = Object.keys(newPopupMenuState);
		for (i = 0; i < keys.length; i++) {
			var key = keys[i];
			var value = newPopupMenuState[key];
			if (popupMenuState[key] !== value) {
				popupMenuStateChanged = true;
				popupMenuState[key] = value;
			}
		}
	}

	itemTypeName = 'InBasket Task';
};

InBasketTaskGrid.prototype.fillPopupMenu = function InBasketTaskGridFillContextMenu(rowId, col) {
	var popupMenu = grid.getMenu();
	popupMenu.removeAll();
	this.cui.fillPopupMenu('PopupMenuItemGrid', popupMenu, this.getMenuContext(null, rowId, col), popupMenuState);
	this.cui.callInitHandlersForPopupMenu({}, '');
};

InBasketTaskGrid.prototype.openCompletionDialog = function InBasketTaskGridOpenCompletionDialog(itemId, itemTypeName) {
	//purpose: to delay modal dialog opening when the dialog has controls.
	var showModalDialogWithDelay = function(url, paramsObj, windowOptions, doRepopulateAfterDialog) {
		setTimeout(function() {
			windowOptions.resizable = true;
			windowOptions.scroll = true;
			windowOptions.status = false;
			windowOptions.help = false;
			paramsObj.content = url;
			paramsObj.isPopup = true;
			var dialog = window.parent.ArasModules.Dialog.show('iframe', Object.assign({}, paramsObj, windowOptions));
			dialog.promise.then(function(data) {
				if (data && data.updated) {
					const itemsGridArray = topWnd.arasTabs.getSearchGridTabs(itemTypeID);
					itemsGridArray.forEach(function(itemsGrid) {
						itemsGrid.doSearch();
					});
				}
			});
		}, 10);
	};

	function getItemFromServer(amlQuery) {
		var tmpRes = arasObj.soapSend('ApplyItem', amlQuery);
		if (tmpRes.getFaultCode() !== 0) {
			arasObj.AlertError(tmpRes);
			return null;
		}
		return tmpRes.getResult().selectSingleNode('Item');
	}

	var item = new Item(itemTypeName, 'get');
	item.setID(itemId);
	item = item.apply();
	var itemNd = item.node;
	var lockedById = arasObj.getItemProperty(itemNd, 'locked_by_id');
	var error;
	var wndOptions;
	var params;

	if (lockedById !== '' && lockedById !== userID) {
		error = 'itemsgrid.unable_complete_task_claimed_by_someone_else';
	} else {
		if (itemNd.getAttribute('type') === 'Workflow Task') {
			params = {
				aras: arasObj,
				activity: getItemFromServer(
					'<Item type=\'Activity\' action=\'get\'>' +
						'<Relationships>' +
							'<Item type=\'Activity Assignment\' action=\'get\'><id>' + itemNd.getAttribute('id') + '</id></Item>' +
							'<Item type=\'Activity Task\' action=\'get\'/>' +
							'<Item type=\'Activity Variable\' action=\'get\'/>' +
							'<Item type=\'Workflow Process Path\' action=\'get\'/>' +
						'</Relationships>' +
					'</Item>'),
				wflName: arasObj.getItemPropertyAttribute(itemNd, 'container', 'keyed_name'),
				wflId: arasObj.getItemProperty(itemNd, 'container'),
				assignmentId: itemNd.getAttribute('id'),
				itemId: arasObj.getItemProperty(itemNd, 'item')
			};
			wndOptions = {dialogHeight:  550 , dialogWidth: 700};

			showModalDialogWithDelay('InBasket/InBasket-VoteDialog.aspx', params, wndOptions);
		} else if (itemNd.getAttribute('type') === 'Project Task') {
			var acwFormNd = arasObj.getFormForDisplay('Activity Completion Worksheet', 'by-name', false);
			var formWidth;
			var formHeight;
			if (acwFormNd && acwFormNd.node) {
				formWidth = parseInt(aras.getItemProperty(acwFormNd.node, 'width'));
				formHeight = parseInt(aras.getItemProperty(acwFormNd.node, 'height'));
			}
			var tmpRes = getItemFromServer(
				'<Item type=\'Activity2\' action=\'get\' select=\'id\'>' +
					'<OR>' +
						'<id>' + itemNd.getAttribute('id') + '</id>' +
						'<id condition=\'in\'>SELECT source_id FROM Activity2_Assignment WHERE id=\'' + itemNd.getAttribute('id') + '\'</id>' +
					'</OR>' +
				'</Item>');
			if (tmpRes) {
				wndOptions = {dialogWidth: formWidth || 700, dialogHeight:  800};

				window.focus();
				showModalDialogWithDelay('../Solutions/Project/scripts/ActivityCompletionWorksheet/ACWDialog.html', [window, tmpRes.getAttribute('id')], wndOptions);
			}

		} else if (itemNd.getAttribute('type') === 'FMEA Task') {
			var fmeaAction = getItemFromServer('<Item type=\'FMEA Action\' action=\'get\' select=\'milestone_comment,milestone_name,' +
				'milestone_due_date\' id=\'' + itemNd.getAttribute('id') + '\'></Item>');
			params = {
				aras: arasObj,
				itemId: itemNd.getAttribute('id'),
				itemName: arasObj.getItemProperty(fmeaAction, 'milestone_name'),
				itemComments: arasObj.getItemProperty(fmeaAction, 'milestone_comment'),
				itemParent: arasObj.getItemPropertyAttribute(itemNd, 'container', 'keyed_name'),
				itemParentId: arasObj.getItemProperty(itemNd, 'container'),
				itemParentType: arasObj.getItemPropertyAttribute(itemNd, 'container', 'type'),
				itemDueDate: arasObj.getItemProperty(fmeaAction, 'milestone_due_date'),
				'part_number': arasObj.getItemPropertyAttribute(itemNd, 'item', 'keyed_name'),
				lockedById: arasObj.getItemProperty(itemNd, 'locked_by_id')
			};
			wndOptions = (params.itemParentType === 'Process Planner') ? {dialogHeight: 695, dialogWidth: 700} : {dialogHeight: 510, dialogWidth: 700};
			showModalDialogWithDelay(arasObj.getScriptsURL() + '../Solutions/QP/scripts/MyTasksCompletionDialog.html', params, wndOptions, true);
		} else {
			var formTypeCompleteValue = 'complete';
			var formId = arasObj.uiGetFormID4ItemEx(itemNd, formTypeCompleteValue);

			if (!formId) {
				arasObj.AlertError(arasObj.getResource('', 'ui_methods_ex.form_not_specified_for_you', formTypeCompleteValue));
				return null;
			}

			var formNd = arasObj.getFormForDisplay(formId);

			formNd = formNd ? formNd.node : null;

			var param = {
				aras: arasObj,
				title: arasObj.getResource('', 'itemsgrid.completion_dialog'),
				item: item,
				formId: formId
			};

			var width = aras.getItemProperty(formNd, 'width') || 400;
			var height = aras.getItemProperty(formNd, 'height') || 300;
			showModalDialogWithDelay('ShowFormAsADialog.html', param, {dialogHeight: height, dialogWidth: width});
		}
	}
	return error ? arasObj.getResource(null, error) : null;
};

InBasketTaskGrid.prototype.onEditCommand = function InBasketTaskGridOnEditCommand(itemId) {
	return !this.showError(this.openCompletionDialog(itemId, itemTypeName));
};

InBasketTaskGrid.prototype.onDoubleClick = function InBasketTaskGridOnDoubleClick(itemId) {
	return !this.showError(this.openCompletionDialog(itemId, itemTypeName));
};

InBasketTaskGrid.prototype.onLink = function InBasketTaskGridOnLink(typeName, id) {
	switch (typeName) {
		case 'Workflow Process':
			var item = arasObj.getItemById(typeName, id, 0);
			var params = {};
			params.aras = arasObj;
			params.processID = id;
			params.processName = arasObj.getItemProperty(item, 'name');
			params.dialogWidth = 850;
			params.dialogHeight = 470;
			params.content = 'WorkflowProcess/WflProcessViewer.aspx';

			var win = arasObj.getMostTopWindowWithAras(window);
			(win.main || win).ArasModules.Dialog.show('iframe', params);
			break;
		case 'InBasket Task':
			this.showError(this.openComplitionDialog(id, typeName));
			break;
		default:
			InBasketTaskGrid.superclass.onLink(typeName, id);
	}
};

InBasketTaskGrid.prototype.onMenuClicked = function InBasketTaskGridOnMenuClicked(m, rowId, col) {
	switch (m) {
		case 'locked_criteria:clear':
			grid.setCellValue('input_row', 0, '<img src=\'\'>');
			break;
		case 'locked_criteria:by_me':
			grid.setCellValue('input_row', 0, '<img src=\'../images/ClaimedByMe.svg\'>');
			break;
		case 'locked_criteria:by_others':
			grid.setCellValue('input_row', 0, '<img src=\'../images/ClaimedByOthers.svg\'>');
			break;
		case 'locked_criteria:by_anyone':
			grid.setCellValue('input_row', 0, '<img src=\'../images/ClaimedByAnyone.svg\'>');
			break;
		default:
			break;
	}

	return m;
};

window['onAction:1020CBF7E25E4479A260FA5AF4E4A378:BC7977377FFF40D59FF14205914E9C71Command'] = function() {
	var itemId = grid.getSelectedId();
	var item = new Item(itemTypeName, 'get');
	item.setAttribute('select', 'config_id, container');
	item.setID(itemId);
	item = item.apply();

	var idActivity = item.getProperty('config_id');
	var projectId = item.getProperty('container');

	var projectNumber;
	var wbsId;
	var wbs;

	var project = aras.getItem('Project', '@id=\'' + projectId + '\'', '<id>' + projectId + '</id>');
	if (project) {
		wbsId = aras.getItemProperty(project, 'wbs_id');
		projectNumber = aras.getItemProperty(project, 'project_number');
	}

	eval(aras.getFileText(aras.getBaseURL() + '/Solutions/Project/javascript/gantt_methods.js'));
	eval(aras.getFileText(aras.getBaseURL() + '/Solutions/Project/javascript/scheduling_methods.js'));

	function showGanttChart(wbsId, projectNumber) {
		wbs = getWBS(wbsId);
		initActNums();
		sortItems(wbs.documentElement);
		showGanttInternal(wbs, projectNumber);
	}

	function getWBS(wbsId) {
		var xml = aras.createXMLDocument();
		var query = aras.createXMLDocument();

		query.load(aras.getI18NXMLResource('query.xml', aras.getScriptsURL() + '../Solutions/Project/'));
		query.selectSingleNode('//*[@repeatTimes]').setAttribute('repeatTimes', -1);
		query.documentElement.setAttribute('id', wbsId);
		var result = aras.applyItem(query.documentElement.xml);

		xml.loadXML(result);
		return xml;
	}

	showGanttChart(wbsId, projectNumber);
};

/** ItemsGrid\previewPane.js **/
var previewPane = (function() {
	var previewPaneType = null;
	var lastItemId = null;

	function hideProperties() {
		if (document.querySelector('#formpreview_container')) {
			var elem = document.getElementById('itemProperties');
			elem.classList.add('hideImportant');
		}
	}

	function hideForm() {
		if (document.querySelector('#formpreview_container')) {
			document.getElementById('formpreview_container').style.display = 'none';
			document.getElementById('formpreview_splitter').style.display = 'none';
			document.getElementById('formpreview_container').style.height = '0';
			document.getElementById('gridTD').style.height = 'calc(100% - 46px)';
			document.getElementById('grid_container').style.height = '100%';
		}
		lastItemId = null;
	}
	var showTypeFunctions = {
		Form: function() {
			hideProperties();
			var frame = document.getElementById('formpreview_container');
			if (frame) {
				frame.style.display = 'block';
				document.getElementById('formpreview_splitter').style.display = 'block';
				document.getElementById('grid_container').style.height = document.body.offsetHeight / 2 + 'px';

				var iframe = document.querySelector('#formpreview_container iframe');
				if (!iframe.src) {
					iframe.addEventListener('load', function listener() {
						iframe.contentWindow.formPreview.errorMessage = aras.getResource('', 'itemsgrid.error_open_form_preview');
						iframe.contentWindow.formPreview.defaultMessage = aras.getResource('', 'itemsgrid.no_preview_available');
						iframe.contentWindow.formPreview.clearForm();
						iframe.removeEventListener('load', listener);
					});
					iframe.src = '../Modules/formPreview/formPreview.html';
				}
			}

			if (document.querySelector('#formpreview_container')) {
				var selectItems = grid.getSelectedItemIDs();
				if (selectItems && selectItems[selectItems.length - 1]) {
					onClickRow(selectItems[selectItems.length - 1]);
				}
			}
		},
		Properties: function() {
			hideForm();
			if (document.getElementById('itemProperties')) {
				var elem = document.getElementById('itemProperties');
				elem.classList.remove('hideImportant');
			}
		},
		Off: function() {
			hideForm();
			hideProperties();
		},
	};

	return {
		getType: function() {
			return previewPaneType;
		},

		setType: function(newPreviewPaneType) {
			if (showTypeFunctions[newPreviewPaneType]) {
				previewPaneType = newPreviewPaneType;
				showTypeFunctions[newPreviewPaneType]();
			}
		},

		showFormByItemId: function(itemId, itemTypeName) {
			if (!itemTypeName || !itemId || itemId === lastItemId || !document.querySelector('#formpreview_container')) {
				return;
			}
			lastItemId = itemId;
			var formFrame = document.querySelector('#formpreview_container iframe');
			if (formFrame && formFrame.contentWindow.formPreview) {
				formFrame.contentWindow.formPreview.showItem(itemTypeName, itemId, aras);
			} else if (formFrame) {
				lastItemId = null;
				formFrame.addEventListener('load', function listener() {
					formFrame.removeEventListener('load', listener);
					this.showFormByItemId(itemId, itemTypeName);
				}.bind(this));
			}
		},

		clearForm: function(itemId) {
			if (itemId && itemId !== lastItemId) {
				return;
			}
			var formFrame = document.querySelector('#formpreview_container iframe');
			if (formFrame && formFrame.contentWindow && formFrame.contentWindow.formPreview) {
				formFrame.contentWindow.formPreview.clearForm();
			}
		},

		updateForm: function(itemId, itemTypeName) {
			if (itemId === lastItemId) {
				var formFrame = document.querySelector('#formpreview_container iframe');
				if (formFrame && formFrame.contentWindow.formPreview) {
					formFrame.contentWindow.formPreview.showItem(itemTypeName, itemId, aras);
				}
			}
		},
	};
})();

/** Error occured: "ItemsGrid\itemsMenu.js" not found **/

/** UserReports.js **/
var userReportsCache = {itemTypeId: '', reports: null};
function getItemTypeUserReports(itemTypeId, reloadCache) {
	if (reloadCache) {
		resetUserReportsCache();
	}
	if (userReportsCache.itemTypeId == itemTypeId) {
		return userReportsCache.reports;
	}
	var userReports = aras.newIOMItem('Method', 'GetSelfServiceReports');
	userReports.setProperty('base_item_type', itemTypeId);
	userReportsCache = {itemTypeId: itemTypeId, reports: userReports.apply()};
	return userReportsCache.reports;
}

function resetUserReportsCache() {
	userReportsCache = {itemTypeId: '', reports: null};
}

function runUserReport(aras, cmdID, instances) {
	///<param name="instances">string like &quot;'item_id1','item_id2'&quot;</param>
	var arr = cmdID.split(':');
	var selectedId = arr[1];
	var report = aras.getItemFromServer('SelfServiceReport', arr[1]);
	if (!report) {
		return;
	}
	runUserReportCommon(selectedId, report, aras, instances);
}

function runUserReportCommon(selectedId, report, aras, instances) {
	///<param name="instances">string like &quot;'item_id1','item_id2'&quot;</param>
	var isreportSetValid = aras.newIOMItem('Method', 'IsOldReportSet');
	isreportSetValid.setID(report.getID());
	isreportSetValid = isreportSetValid.apply();

	if (isreportSetValid.isError()) {
		aras.AlertError(isreportSetValid.getErrorString());
		return;
	}

	if (isreportSetValid.getResult() == '0') {
		aras.AlertWarning(aras.getResource('../Modules/aras.innovator.Izenda/', 'servicereporting.report_definitions_inconsistencies'));
		return;
	}

	var win = aras.uiFindAndSetFocusWindowEx(selectedId);
	if (win) {
		return;
	}

	if (hasExcludedProperties(report, aras)) {
		aras.AlertWarning(aras.getResource('../Modules/aras.innovator.Izenda/', 'servicereporting.report_contains_restricted_data'));
		return;
	}

	var i18nSessionContext = aras.IomInnovator.getI18NSessionContext();
	var url = aras.getUserReportServiceBaseUrl() + '/ReportViewer.aspx?';
	var params = 'rn=' + encodeURIComponent(selectedId) + '&itemid=' + encodeURIComponent(selectedId) +
			'&access_token=' + aras.OAuthClient.getToken() +
			'&LOCALE=' + encodeURIComponent(i18nSessionContext.getLocale()) +
			'&TIMEZONE_NAME=' + encodeURIComponent(i18nSessionContext.getTimeZone()) +
			'&ITEMTYPEMODE=itm_all' +
			'&CLIENTURL=' + encodeURIComponent(aras.getBaseURL());
	var fullUrl = url + params;

	// REsets context_item_ids in (report item id + authinfo)/params map
	var xmlHttp = new XMLHttpRequest();
	var mapUrl = aras.getUserReportServiceBaseUrl() + '/rs2.aspx';
	xmlHttp.onreadystatechange = function(xhr) {
		if (xmlHttp.readyState == 4) {
			if (xmlHttp.status == 200) {
				win = aras.targetReport(report.node, 'service', fullUrl, '', true);
				win.getItem = function() {
					return report.node;
				};
				setTimeout(function() {
					aras.uiRegWindowEx(selectedId, win);
				}, 0);
			} else {
				aras.AlertError(aras.getResource('', 'common.web_request_error').replace('{0}', xmlHttp.status).replace('{1}', mapUrl).replace('{2}', xmlHttp.statusText));
				return;
			}
		}
	};
	xmlHttp.open('POST', mapUrl + '?op=MAP_CONTEXT_ITEM_IDS&_random=' + aras.GUIDManager.GetGUID() + '&' + params, false);
	if (fullUrl.length > 2000) {
		xmlHttp.setRequestHeader('Content-type', 'application/x-www-form-urlencoded');
		xmlHttp.setRequestHeader('Content-length', instances.length);
	}
	i18nSessionContext = aras.IomInnovator.getI18NSessionContext();
	xmlHttp.setRequestHeader('LOCALE', i18nSessionContext.getLocale());
	xmlHttp.setRequestHeader('TIMEZONE_NAME', i18nSessionContext.getTimeZone());
	xmlHttp.send(instances);

	var runReportByUser = aras.newIOMItem('Method', 'AddOrEditRunReportByUser');
	runReportByUser.setID(selectedId);
	runReportByUser = runReportByUser.apply();
	if (runReportByUser.isError()) {
		aras.AlertError(runReportByUser.getErrorString());
	}
}

function hasExcludedProperties(report, aras) {
	var reportSet = report.getProperty('definition');
	if (reportSet) {
		var rsXml = aras.createXMLDocument();
		rsXml.loadXML(reportSet);
		var reportXml = rsXml.selectSingleNode('//Report');
		if (reportXml) {
			var selection = reportXml.selectSingleNode('//Selections');
			if (selection) {
				var selections = selection.selectNodes('//Selection');
				if (selections.length) {
					var request = aras.newIOMItem('Method', 'IsReportContainsExcludedProps');
					for (var i = 0; i < selections.length; i++) {
						var rel = aras.newIOMItem('ItemType');
						rel.setProperty('db_name', selections[i].getAttribute('ColumnName'));
						request.addRelationship(rel);
					}

					request = request.apply();
					var isReportContainsExcludedProps = request.getResult();
					if (isReportContainsExcludedProps == 'true') {
						return true;
					}
				}
			}
		}
	}

	return false;
}

/** ..\Modules\aras.innovator.ExtendedClassification\scripts\xPropertiesUtils.js **/
(function(wnd) {
	var xPropertiesUtils = {
		isItemTypeAllowedOnTree: function(itemTypeId) {
			var treesData = wnd.aras.MetadataCache.GetAllXClassificationTrees();
			var iTNodes = treesData.selectSingleNode('Item[@type="xClassificationTree" and (Relationships/Item[@type="xClassificationTree_ItemType"]/' +
				'related_id/Item[@type="ItemType" and @id="' + itemTypeId + '"] or Relationships/Item[@type="xClassificationTree_ItemType"]' +
				'/related_id="' + itemTypeId + '")]');

			return !!iTNodes;
		},
		getXClassificationTreesForItemType: function(itemTypeId) {
			var treesData = wnd.aras.MetadataCache.GetAllXClassificationTrees();
			return ArasModules.xml.selectNodes(treesData, 'Item[@type="xClassificationTree" and (Relationships/Item[@type="xClassificationTree_ItemType"]/' +
				'related_id/Item[@type="ItemType" and @id="' + itemTypeId + '"] or Relationships/Item[@type="xClassificationTree_ItemType"]' +
				'/related_id="' + itemTypeId + '")]');
		},
		getClassificationHierarchyByClassId: function(xClassId) {
			var treesData = wnd.aras.MetadataCache.GetAllXClassificationTrees();
			var xClassNd = treesData.selectSingleNode('Item[@type="xClassificationTree"]/Relationships/Item[@type="xClass" and @id="' + xClassId + '"]');
			var parentTreeNd = xClassNd.parentNode.parentNode;
			var classificationHierarchy = JSON.parse(wnd.aras.getItemProperty(parentTreeNd, 'classification_hierarchy'));
			return {
				hierarchy: classificationHierarchy,
				classRefId: wnd.aras.getItemProperty(xClassNd, 'ref_id'),
				treeId: parentTreeNd.getAttribute('id')
			};
		},
		getParentXClassesInHierarchy: function(data) {
			var treesData = wnd.aras.MetadataCache.GetAllXClassificationTrees();
			var refIds = [data.classRefId];

			var hierarchyNode;
			var toRefId = data.classRefId;

			var findHandler = function(elt) { return elt.toRefId === toRefId; };
			hierarchyNode = data.hierarchy.find(findHandler);
			while (hierarchyNode) {
				if (hierarchyNode.fromRefId) {
					refIds.push(hierarchyNode.fromRefId);
					toRefId = hierarchyNode.fromRefId;
					hierarchyNode = data.hierarchy.find(findHandler);
				} else {
					hierarchyNode = null;
				}
			}

			var refIdStatement = refIds.map(function(refId) {return 'ref_id="' + refId + '"';}).join(' or ');
			var xClassNodes = ArasModules.xml.selectNodes(treesData, 'Item[@type="xClassificationTree" and @id="' + data.treeId +
				'"]/Relationships/Item[@type="xClass" and (' + refIdStatement + ')]');

			return xClassNodes.map(function(xClass) {return xClass.getAttribute('id');});
		},
		getXPropertiesByClasses: function(xClassIds) {
			var treesData = wnd.aras.MetadataCache.GetAllXClassificationTrees();
			var xClassesSelectStatement = xClassIds.map(function(e) {return '@id="' + e + '"';}).join(' or ');
			return ArasModules.xml.selectNodes(treesData, 'Item[@type="xClassificationTree"]/Relationships/Item[@type="xClass" and (' +
				xClassesSelectStatement + ')]/Relationships/Item[@type="xClass_xPropertyDefinition"]/related_id/Item');
		},
		getXPropertiesForXClasses: function(classIds) {
			var result = {};
			classIds.forEach(function(classId) {
				var hierarchyData = this.getClassificationHierarchyByClassId(classId);
				var classWithParents = this.getParentXClassesInHierarchy(hierarchyData);
				result[classId] = this.getXPropertiesByClasses(classWithParents);
			}.bind(this));
			return result;
		},
		getJSON: function(xPropertiesHash) {
			var result = [];
			var xClassIds = Object.keys(xPropertiesHash);
			xClassIds.forEach(function(xClassId) {
				result.push(this.getXClassJSON(xClassId, xPropertiesHash[xClassId]));
			}.bind(this));

			return result;
		},
		getXClassJSON: function(xClassId, xPropertyCollection) {
			var treesData = wnd.aras.MetadataCache.GetAllXClassificationTrees();
			var result = {};
			var xClassNode = treesData.selectSingleNode('Item[@type="xClassificationTree"]/Relationships/Item[@type="xClass" and @id="' + xClassId + '"]');
			var sortOrderString = wnd.aras.getItemProperty(xClassNode, 'xproperties_sort_order');

			result.id = xClassId;
			result.label = wnd.aras.getItemProperty(xClassNode, 'label') || wnd.aras.getItemProperty(xClassNode, 'name') ;
			result.properties = xPropertyCollection.reduce(function(result, xPropertyNode) {
				if (wnd.aras.getItemProperty(xPropertyNode.parentNode.parentNode, 'inactive') !== '1') {
					result.push(this.getXPropertyJSON(xPropertyNode));
				}
				return result;
			}.bind(this), []);

			if (sortOrderString) {
				var sortOrderArr = sortOrderString.split(',');
				var sortOrderJSON = {};
				sortOrderArr.forEach(function(key, idx) {
					sortOrderJSON[key] = idx + 1;
				});

				result.properties = result.properties.sort(function(prop1, prop2) {
					return sortOrderJSON[prop1.id] < sortOrderJSON[prop2.id] ? -1 : 1;
				});
			}

			return result;
		},
		getXPropertyJSON: function(xPropertyNode) {
			var result = {};
			var relationshipNode = xPropertyNode.parentNode.parentNode;

			result.id = xPropertyNode.getAttribute('id');
			result.dataSource = wnd.aras.getItemProperty(xPropertyNode, 'data_source', null);
			result.name = wnd.aras.getItemProperty(xPropertyNode, 'name');
			result.type = wnd.aras.getItemProperty(xPropertyNode, 'data_type');
			result.pattern = wnd.aras.getItemProperty(xPropertyNode, 'pattern');
			result.prec = wnd.aras.getItemProperty(xPropertyNode, 'prec');
			result.scale = wnd.aras.getItemProperty(xPropertyNode, 'scale');
			result.helpTooltip = wnd.aras.getItemProperty(xPropertyNode, 'help_tooltip');
			result.privatePermissionBehavior = wnd.aras.getItemProperty(xPropertyNode, 'private_permission_behavior');

			// overridable properties
			result.isInactive = +(wnd.aras.getItemProperty(relationshipNode, 'inactive')) === 1;
			result.isReadonly = +(wnd.aras.getItemProperty(relationshipNode, 'readonly')) === 1;
			result.isRequired = +(wnd.aras.getItemProperty(relationshipNode, 'is_required')) === 1;
			result.default_value = wnd.aras.getItemProperty(relationshipNode, 'default_value', null);
			result.label = wnd.aras.getItemProperty(relationshipNode, 'label', null) || wnd.aras.getItemProperty(xPropertyNode, 'name');

			if (result.type === 'list' || result.type === 'color list' || result.type === 'mv_list') {
				result.values = this.getListValues(result.dataSource);
			}

			return result;
		},
		getMetadataForXClassesControl: function(xClassIds) {
			var hash = this.getXPropertiesForXClasses(this.sortXClassIdsAccordingWithTrees(xClassIds));
			return this.getJSON(hash);
		},
		getListValues: function(listId) {
			var res = wnd.aras.MetadataCache.GetList([listId], []);
			var listValues = ArasModules.xml.selectNodes(res.getResult(), 'Item/Relationships/Item');
			return listValues.map(function(valueNd) {
				return {
					label: wnd.aras.getItemProperty(valueNd, 'label'),
					value: wnd.aras.getItemProperty(valueNd, 'value')
				};
			});
		},
		getParentClassesChain: function(xClass, tree) {
			var childToParentIds = {};
			var hieararchy = JSON.parse(aras.getItemProperty(tree, 'classification_hierarchy'));
			hieararchy.forEach(function(edge) {
				childToParentIds[edge.toRefId] = edge.fromRefId;
			});
			var parentChain = [];
			var getParentId = function(childId) {
				var parentId = childToParentIds[childId];
				if (parentId) {
					var xClass = tree.selectSingleNode('Relationships/Item[ref_id=\'' + parentId + '\']');
					parentChain.push(xClass);
					getParentId(parentId);
				}
			};
			getParentId(aras.getItemProperty(xClass, 'ref_id'));
			return parentChain;
		},
		getSortOrderForProperties: function(xClass, tree, xProps, deletedXProps) {
			var parentXClassChain = this.getParentClassesChain(xClass, tree);
			deletedXProps = deletedXProps || [];
			Array.prototype.forEach.call(deletedXProps, function(deletedXProp) {
				aras.setItemProperty(deletedXProp.selectSingleNode('related_id/Item'), 'sort_order', '');
			});
			var sortOrder = aras.getItemProperty(xClass, 'xproperties_sort_order');
			if (!sortOrder) {
				sortOrder = parentXClassChain.reduceRight(function(prev, curr) {
					var sortOrder = aras.getItemProperty(curr, 'xproperties_sort_order');
					if (!prev && sortOrder) {
						return sortOrder;
					}
					return prev;
				}, null);
			}
			if (sortOrder) {
				var sortOrderArr = sortOrder.split(',');
				sortOrder = {};
				sortOrderArr.forEach(function(key, idx) {
					sortOrder[key] = idx;
				});
			}
			var propIdToSort = {};
			var unsortedProps = Array.prototype.reduce.call(xProps, function(prev, curr) {
				var sortIdx = sortOrder && sortOrder[aras.getItemProperty(curr.selectSingleNode('related_id/Item'), 'id')];
				if (Number.isInteger(sortIdx)) {
					propIdToSort[aras.getItemProperty(curr, 'id')] = sortIdx;
				} else {
					prev.push(curr);
				}
				return prev;
			}, []);

			var chainIds = parentXClassChain.map(function(item) {
				aras.getItemRelationshipsEx(item, 'xClass_xPropertyDefinition');
				return aras.getItemProperty(item, 'id');
			}).reverse();
			unsortedProps.sort(function(a, b) {
				var sourceA = tree.selectSingleNode('Relationships/Item[Relationships/Item[@id="' + aras.getItemProperty(a, 'id') + '"]]');
				var sourceB = tree.selectSingleNode('Relationships/Item[Relationships/Item[@id="' + aras.getItemProperty(b, 'id') + '"]]');
				var idxA = chainIds.indexOf(aras.getItemProperty(sourceA, 'id'));
				var idxB = chainIds.indexOf(aras.getItemProperty(sourceB, 'id'));
				var levelA = idxA === -1 ? chainIds.length : idxA;
				var levelB = idxB === -1 ? chainIds.length : idxB;
				var relatedA = a.selectSingleNode('related_id/Item');
				var relatedB = b.selectSingleNode('related_id/Item');
				var labelA = aras.getItemProperty(relatedA, 'label') || aras.getItemProperty(relatedA, 'name');
				var labelB = aras.getItemProperty(relatedB, 'label') || aras.getItemProperty(relatedB, 'name');

				if (levelA < levelB) {
					return -1;
				}
				if (levelA > levelB) {
					return 1;
				}
				if (labelA < labelB) {
					return -1;
				}
				if (labelA > labelB) {
					return 1;
				}
				return 0;
			});

			var sortedCount = xProps.length - unsortedProps.length;
			unsortedProps.forEach(function(xProp, idx) {
				propIdToSort[aras.getItemProperty(xProp, 'id')] = sortedCount + idx;
			});
			return propIdToSort;
		},
		sortXClassIdsAccordingWithTrees: function(xClassIds) {
			var lastXClassIndex = 0;
			var xClassesHash = {};

			var getTreeXClassIds = function(tree) {
				var hierarchy = aras.getItemProperty(tree, 'classification_hierarchy');
				if (!hierarchy) {
					return;
				}
				var treeStructure = JSON.parse(hierarchy);
				var edges = {};
				treeStructure.forEach(function(edge) {
					var from = edge.fromRefId || 'roots';
					var to =  edge.toRefId;
					if (!edges[from]) {
						edges[from] = [];
					}
					edges[from].push(to);
				});

				var xClassRefToId = {};

				ArasModules.xml.selectNodes(tree, './Relationships/Item[@type="xClass"]').reduce(function(res, xClassNd) {
					res[wnd.aras.getItemProperty(xClassNd, 'ref_id')] = xClassNd.getAttribute('id');
					return res;
				}, xClassRefToId);

				var linearizeXClasses = function(parentRefId) {
					xClassesHash[xClassRefToId[parentRefId]] = lastXClassIndex++;
					var children = edges[parentRefId] || [];

					children.forEach(function(childId) {
						if (edges[childId]) {
							linearizeXClasses(childId);
						} else {
							xClassesHash[xClassRefToId[childId]] = lastXClassIndex++;
						}
					});
				};

				edges.roots.forEach(function(rootId) {
					linearizeXClasses(rootId);
				});
			};

			if (!Array.isArray(xClassIds) && xClassIds.forEach) {
				// if Set was received need convert it to Array
				var xClassIdsArray = [];
				xClassIds.forEach(function(id) { xClassIdsArray.push(id); });
				xClassIds = xClassIdsArray;
			} else {
				// to avoid source array changes
				xClassIds = xClassIds.slice();
			}

			var treesData = wnd.aras.MetadataCache.GetAllXClassificationTrees();

			var trees = ArasModules.xml.selectNodes(treesData, './Item[@type="xClassificationTree"]');

			trees.forEach(function(tree) {
				getTreeXClassIds(tree);
			});

			xClassIds.sort(function(id1, id2) {
				return xClassesHash[id1] < xClassesHash[id2] ? -1 : 1;
			});

			return xClassIds;
		},
		getSetOfXPropertiesNamesForXClasses: function(xClassIds) {
			var hash = this.getXPropertiesForXClasses(xClassIds);
			var result = new Set();

			xClassIds.forEach(function(xClassId) {
				hash[xClassId].forEach(function(xPropDefNd) {
					result.add(aras.getItemProperty(xPropDefNd, 'name'));
				});
			});

			return result;
		},
		deleteUndefinedXPropertiesFromItem: function(item) {
			var relationshipType = item.getAttribute('type') + '_xClass';
			var relationships = item.selectNodes('Relationships/Item[@type="' + relationshipType + '" and not(@action="delete") and not(@action="skip")]');
			var iomItem = aras.newIOMItem();
			var xClassIDs = Array.prototype.map.call(relationships, function(relationship) {
				iomItem.node = relationship;
				return iomItem.getRelatedItemID();
			});

			var xPropertiesNamesSet = this.getSetOfXPropertiesNamesForXClasses(new Set(xClassIDs));
			xPropNodes = ArasModules.xml.selectNodes(item, './*[starts-with(name(),"xp-")]');
			xPropNodes.forEach(function(xPropNode) {
				if (!xPropertiesNamesSet.has(xPropNode.nodeName)) {
					xPropNode.parentNode.removeChild(xPropNode);
				}
			});
		},
		getItemXClassIds: function(item) {
			var result = [];
			var relationshipType = item.getAttribute('type') + '_xClass';
			var relationships = ArasModules.xml.selectNodes(item, 'Relationships/Item[@type="' + relationshipType +
				'" and (not(@action="delete") and not(@action="skip"))]');
			relationships.forEach(function(relNode) {
				var id = aras.getItemProperty(relNode, 'related_id');
				result.push(id);
			});

			return result;
		},
		sortXClassRelationships: function(item) {
			var relationshipType = item.getAttribute('type') + '_xClass';
			var relationshipsNode = ArasModules.xml.selectSingleNode(item, 'Relationships');
			var relationships = ArasModules.xml.selectNodes(item, 'Relationships/Item[@type="' + relationshipType + '" and @action="add"]');

			// reverse array to save initial sorting
			relationships.reverse();

			relationships.forEach(function(relshipNode) {
				relationshipsNode.insertBefore(relshipNode, relationshipsNode.firstChild);
			});
		},
		checkPropertiesBeforeItemSave: function(item, xClassesControl) {
			var propertiesForCheck = [];
			var xClassesIds = this.getItemXClassIds(item);
			var propertiesData = this.getMetadataForXClassesControl(xClassesIds);

			propertiesData.forEach(function(xClassData) {
				xClassData.properties.forEach(function(propertyData) {
					if (propertyData.isRequired &&
						item.selectSingleNode(propertyData.name + '[@is_null=0]') === null &&
						aras.getItemProperty(item, propertyData.name) === '') {
						propertiesForCheck.push({name: propertyData.name, label: propertyData.label, default_value: propertyData.default_value});
					}
				});
			});

			var errorMessage = null;
			var errorProperty = propertiesForCheck.find(function(propertyData) {
				return propertyData.default_value === undefined;
			});

			if (errorProperty) {
				return aras.AlertError(aras.getResource('', 'item_methods_ex.field_required_provide_value', errorProperty.label))
				.then(function() {
					return false;
				});
			} else {
				for (var i = 0; i < propertiesForCheck.length; i++) {
					var propertyData = propertiesForCheck[i];

					var ask = aras.confirm(aras.getResource('', 'item_methods_ex.field_required_default_will_be_used', propertyData.label, propertyData.default_value));
					if (ask) {
						aras.setItemProperty(item, propertyData.name, propertyData.default_value);
						xClassesControl.setPropertyValue(propertyData.name, propertyData.default_value);
					} else {
						return Promise.resolve(false);
					}
				}
			}

			xPropertiesUtils.deleteUndefinedXPropertiesFromItem(item);

			return Promise.resolve(true);
		},
		refreshInitXPropertiesValues: function(item, initPropsHash) {
			Object.keys(initPropsHash).forEach(function(key) { delete initPropsHash[key]; });
			var propsToSelect = [];

			var setPropertyInitialValue = function(propNode, initPropsHash) {
				if (propNode.getAttribute('is_null') === '0') {
					initPropsHash[propNode.nodeName + '@restricted'] = true;
				} else if (propNode.getAttribute('is_null') === '1') {
					initPropsHash[propNode.nodeName] = null;
				} else {
					initPropsHash[propNode.nodeName] = propNode.text;
				}
			};

			var itemXClassIDs = xPropertiesUtils.getItemXClassIds(item);
			var xClassXPropertiesData = xPropertiesUtils.getMetadataForXClassesControl(itemXClassIDs);
			xClassXPropertiesData.forEach(function(xClassData) {
				xClassData.properties.forEach(function(propertyData) {
					if (propertyData.default_value) {
						initPropsHash[propertyData.name] = propertyData.default_value;
					}
				});
			});

			ArasModules.xml.selectNodes(item, './*[starts-with(name(),"xp-")]').forEach(function(propNode) {
				if (propNode.getAttribute('set') && propNode.getAttribute('set').indexOf('value') !== -1 && item.getAttribute('isTemp') !== '1') {
					propsToSelect.push(propNode.nodeName);
				} else if (!(propNode.getAttribute('set') && propNode.getAttribute('set').indexOf('value') !== -1)) {
					setPropertyInitialValue(propNode, initPropsHash);
				}
			});

			if (propsToSelect.length) {
				return ArasModules.soap('<Item type="' + item.getAttribute('type') + '" action="get" id="' + item.getAttribute('id') +
					'" select="' + propsToSelect.join() + '" />', {async: true}).then(function(resp) {
					ArasModules.xml.selectNodes(resp, 'Item/*[starts-with(name(),"xp-")]').forEach(function(propNode) {
						setPropertyInitialValue(propNode, initPropsHash);
					});
				});
			}

			return Promise.resolve();
		},
		refreshInitXPropertiesPermissions: function(item, initPropsHash, needRequest) {
			if (needRequest) {
				let itemWithAllXProps = new Item(item.getAttribute('type'), 'get');
				itemWithAllXProps.setAttribute('id', item.getAttribute('id'));
				itemWithAllXProps.setAttribute('select', 'xp-*(@permission_id)');
				itemWithAllXProps = itemWithAllXProps.apply();
				if (!itemWithAllXProps.isEmpty() && !itemWithAllXProps.isError()) {
					item = itemWithAllXProps.node;
				}
			}
			Object.keys(initPropsHash).forEach(function(key) { delete initPropsHash[key]; });
			ArasModules.xml.selectNodes(item, './*[starts-with(name(),"xp-")]').forEach(function(xPropNode) {
				initPropsHash[xPropNode.tagName] = xPropNode.getAttribute('permission_id');
			});
		}
	};

	wnd.xPropertiesUtils = xPropertiesUtils;
})(window);

/** ItemsGrid\MainGridFactory.js **/
/*
* ItemType Implementation used to expose ability to modify the main grid behaviour based on ItemType.
*
*/

/*
This function implements inheritance mechanism in JavaScript
*/

function inherit(Child, Parent) {
	var F = function() { };
	F.prototype = Parent.prototype;
	Child.prototype = new F();
	Child.prototype.constructor = Child;
	Child.superclass = Parent.prototype;
}

var MainGridFactory = {

	Create: function MainGridFactoryCreate(itemTypeName) {
		switch (itemTypeName) {
			case 'InBasket Task':
				return new InBasketTaskGrid();
			default:
				return new ItemGrid();
		}
	}
};

/** Aras\Client\Controls\Public\ToolbarWrapper.js **/
/**
 * @class ToolbarWrapper
 * @param {object} args
 * @param {HTMLElement} args.connectNode ~ dom node to which new toolbar would be attached
 * @param {string} [args.connectId] ~ in case connectNode was not provided, node with such id would be used as connectNode
 * @param {boolean} [args.useCompatToolbar] ~ force usage of CompatToolbar(S11-version) over Toolbar(S12-version)
 */

function ToolbarWrapper(args) {
	this.hiddenItems = [];
	this._toolbar = null;
	this._toolbarArgs = args;
	this.toolBarsNode = [];

	if (typeof (arasDocumentationHelper) !== 'undefined') {
		arasDocumentationHelper.registerProperties({});
		arasDocumentationHelper.registerEvents('onClick, onChange, onDropDownItemClick, onKeyDown');
		return;
	}
	this.controlLegacy = this;
	for (var method in this) {
		if (typeof this[method] === 'function') {
			if (method == 'getItem') {
				var yetMethodName = 'getElement';
				this[yetMethodName] = this[method];
			}
			var methodName = method.substr(0, 1).toUpperCase() + method.substr(1);
			this[methodName] = this[method];
		}
	}
}

ToolbarWrapper.prototype = {
	onClick: function(el) {
		this.buttonClick(el);
	},

	buttonClick: function(el) {},

	onChange: function(el) {},

	onKeyDown: function(el, evt) {},

	onDropDownItemClick: function(text) {},

	loadXml: function(filePath) {
		var request = new XMLHttpRequest();
		var self = this;
		request.onload = function() {
			self.loadToolbarFromStr(request.responseText);
		};
		request.open('GET', filePath, false);
		request.send();
	},

	loadToolbarFromStr: function(string) {
		var dom = new XmlDocument();
		dom.loadXML(string);
		var node = dom.selectSingleNode('./toolbarapplet').getAttribute('buttonsize').split(',');
		var toolBars = dom.selectNodes('./toolbarapplet/toolbar');

		for (var j = 0; j < toolBars.length; j++) {
			this.toolBarsNode[toolBars[j].getAttribute('id')] = toolBars[j];
		}
	},

	isToolbarExist: function(id) {
		if (this.toolBarsNode[id]) {
			return true;
		}
		return false;
	},
	showToolbar: function(id) {
		var self = this;
		var elementsWithoutIdsCounter = 0;
		var toolbarWrapper = this._toolbarArgs.connectNode || document.getElementById(this._toolbarArgs.connectId);

		var toolbar = this._toolbar;
		if (toolbar && toolbar.id == id) {
			return;
		}

		if (this.toolBarsNode[id]) {
			if (toolbar) {
				toolbar.id = id;
			} else {
				var container = document.createElement('div');
				container.className = 'toolbar-container';
				container.id = this._toolbarArgs.id;
				const ToolbarConstructor = this._toolbarArgs.useCompatToolbar ? CompatToolbar : Toolbar;
				toolbar = new ToolbarConstructor(container);
				toolbar.id = id;
				toolbarWrapper.appendChild(container);

				toolbar.on('click', function(itemId, event) {
					var targetItem = toolbar.data.get(itemId);
					if (targetItem && targetItem.type === 'button' && !targetItem.disabled) {
						self.onClick(new ToolbarItemWrapper({
							item: targetItem,
							toolbar: self
						}));
					}
				});
				toolbar.on('aras-es-search-click', function(itemId, event) {
					var targetItem = toolbar.data.get(itemId);
					self.onClick(new ToolbarItemWrapper({
						item: targetItem,
						toolbar: self
					}));
				});
				toolbar.on('keydown', function(itemId, event) {
					var targetItem = toolbar.data.get(itemId);
					self.onKeyDown(new ToolbarItemWrapper({
						item: targetItem,
						toolbar: self
					}));
				});
			}

			var toolbarIds = [id];

			if (toolbarIds.indexOf('$EmptyClassification') === -1) {
				toolbarIds.push('$EmptyClassification');
			}

			var items = new Map();
			var imagesArr = [];
			var itemsMapHandler = function(itemNode) {
				var idItem;
				var itemType;
				var newItem;
				if ('getAttribute' in itemNode) {
					idItem = itemNode.getAttribute('id');
					idItem = idItem ? idItem : 'emptyId_' + (++elementsWithoutIdsCounter);
				} else {
					return;
				}

				itemType = itemNode.getAttribute('type') || itemNode.nodeName;
				var imageSRC = itemNode.getAttribute('image') || '';
				const itemLabel = itemNode.getAttribute('label') || '';
				imagesArr.push(imageSRC);
				switch (itemType) {
					case 'button':
						newItem = {
							image: imageSRC,
							type: itemType,
							id: idItem,
							tooltip: itemNode.getAttribute('tooltip'),
							idx: itemNode.getAttribute('idx'),
							disabled: itemNode.getAttribute('disabled') === 'true',
							visible: itemNode.getAttribute('invisible') !== 'true',
							right: itemNode.getAttribute('right'),
							class: itemNode.getAttribute('class'),
							state: itemNode.getAttribute('state') ? false : null
						};
						break;
					case 'separator':
						newItem = {
							type: itemType,
							id: idItem,
							visible: true
						};
						break;
					case 'choice':
						var nodes = itemNode.selectNodes('./choiceitem');
						var options = [];
						for (i = 0; i < nodes.length; i++) {
							var node = nodes[i];
							nodeText = node.text;
							var value = node.getAttribute('id') || nodeText;
							options.push({value: value, label: nodeText});
						}

						var selectorType = itemNode.getAttribute('is');
						newItem = {
							type: !selectorType ? 'select' : selectorType + 'Selector',
							id: idItem,
							tooltip: itemNode.getAttribute('tooltip'),
							idx: itemNode.getAttribute('idx'),
							disabled: itemNode.getAttribute('disabled') === 'true',
							visible: itemNode.getAttribute('invisible') !== 'true',
							right: itemNode.getAttribute('right'),
							options: options,
							value: options[0] ? options[0].value : '',
							label: itemLabel
						};
						break;
					case 'edit':
						newItem = {
							type: 'textbox',
							id: idItem,
							idx: itemNode.getAttribute('idx'),
							tooltip: itemNode.getAttribute('tooltip'),
							disabled: itemNode.getAttribute('disabled') === 'true',
							visible: itemNode.getAttribute('invisible') !== 'true',
							right: itemNode.getAttribute('right'),
							value: itemNode.getAttribute('text') || '',
							size: itemNode.getAttribute('size') || '',
							label: itemLabel
						};
						break;
					case 'drop_down_selector':
						var checkItemNodes = itemNode.selectNodes('./checkitem');
						var checkItemOptions = {};
						var chechedItemValue;
						for (i = 0; i < checkItemNodes.length; i++) {
							var checkItemNode = checkItemNodes[i];
							nodeText = checkItemNode.text;
							var checkItemOptionsValue = checkItemNode.getAttribute('id') || nodeText;
							var checked = checkItemNode.getAttribute('checked') === 'true';
							checkItemOptions[checkItemOptionsValue] = nodeText;
							chechedItemValue = checked ? checkItemOptionsValue : chechedItemValue;
						}

						newItem = {
							type: 'dropdownSelector',
							id: idItem,
							tooltip: itemNode.getAttribute('tooltip'),
							disabled: itemNode.getAttribute('disabled') === 'true',
							visible: itemNode.getAttribute('invisible') !== 'true',
							right: itemNode.getAttribute('right'),
							options: checkItemOptions,
							text: itemNode.getAttribute('text') || '',
							value: chechedItemValue
						};
						break;
					case 'drop_down_button':
						var choiceNodes = itemNode.selectNodes('./choiceitem');
						var choiceOptions = [];
						for (i = 0; i < choiceNodes.length; i++) {
							var choiceNode = choiceNodes[i];
							nodeText = choiceNode.text;
							var choiceValue = choiceNode.getAttribute('id') || nodeText;
							choiceOptions.push({value: choiceValue, label: nodeText});
						}

						newItem = {
							type: 'dropdownButton',
							id: idItem,
							tooltip: itemNode.getAttribute('tooltip'),
							disabled: itemNode.getAttribute('disabled') === 'true',
							visible: itemNode.getAttribute('invisible') !== 'true',
							right: itemNode.getAttribute('right'),
							options: choiceOptions,
							text: itemNode.getAttribute('text') || ''
						};
						break;
					case 'dropdownMenu': {
						const recursiveMenuParse = function(children, nodesMap) {
							const childrenIdArray = [];
							for (let i = 0; i < children.length; i++) {
								const childNode = children[i];

								let childIds = null;
								if (childNode.childNodes.length !== 0) {
									childIds = recursiveMenuParse(childNode.childNodes, nodesMap);
								}

								const nodeType = childNode.nodeName;
								const nodeId = childNode.getAttribute('id');
								childrenIdArray.push(nodeId);
								if (nodeType === 'separator') {
									nodesMap.set(nodeId, {
										type: nodeType
									});
									continue;
								}

								const isChecked = childNode.getAttribute('checked') === 'true';
								const isDisabled = childNode.getAttribute('disabled') === 'true';
								nodesMap.set(nodeId, {
									type: nodeType,
									idx: childNode.getAttribute('idx'),
									label: childNode.getAttribute('name'),
									icon: childNode.getAttribute('icon'),
									children: childIds,
									disabled: isDisabled,
									checked: nodeType === 'checkitem' ? isChecked : undefined
								});
							}

							return childrenIdArray;
						};

						const userMenuXml = window.cui.loadMenuAppletFromCommandBars('MainWindowHeaderUserMenu', {menuId: 'headerUserMenu'});
						const doc = new XmlDocument();
						doc.loadXML(userMenuXml);
						const userMenu = doc.selectNodes('./menuapplet/menubar/menu')[0];
						window.cui.initMenuEvents(self, {prefix: 'com.aras.innovator.cui_default.mwh_'});

						const childNodes = userMenu.childNodes;
						const nodesMap = new Map();
						const childrenArray = recursiveMenuParse(childNodes, nodesMap);
						newItem = {
							type: itemType,
							id: idItem,
							right: itemNode.getAttribute('right'),
							visible: itemNode.getAttribute('invisible') !== 'true',
							disabled: itemNode.getAttribute('disabled') === 'true',
							image: itemNode.getAttribute('image'),
							tooltip: itemNode.getAttribute('tooltip'),
							class: itemNode.getAttribute('class'),
							label: itemNode.text,
							childrenItemsData: nodesMap,
							children: childrenArray
						};
						break;
					}
					default:
						var attrs = Array.prototype.slice.call(itemNode.attributes);
						newItem = {};
						attrs.forEach(function(element) {
							newItem[element.nodeName] = element.value;
						});
						newItem.id = idItem;
						newItem.type = itemType;
						newItem.visible = true;
						newItem.disabled = newItem.disabled === 'true';
						break;
				}
				items.set(idItem, newItem);
			};
			for (var j = 0; j < toolbarIds.length; j++) {
				var toolBarNode = this.toolBarsNode[toolbarIds[j]];
				if (toolBarNode) {
					var childNodes = Array.prototype.slice.call(toolBarNode.childNodes);
					childNodes.forEach(itemsMapHandler);
				}
			}
			ArasModules.SvgManager.load(imagesArr);
			toolbar.data = items;
			this._toolbar = toolbar;
			items.forEach(function(item) {
				if (!item.visible) {
					this.hideItem(item.id);
				}
			}.bind(this));
		}
	},

	showLabels: function(isShow) {
		if (!this._toolbar || isShow === this._toolbar.labeled) {
			return;
		}
		this._toolbar.labeled = isShow;
	},

	show: function() {
		var keys = Object.keys(this.toolBarsNode);
		this.showToolbar(keys[0]);
	},

	getId: function() {
		return this._toolbar.id;
	},

	getToolbarInstance: function() {
		return this._toolbar;
	},

	getItem: function(itemId) {
		var toolbar = this._toolbar;
		var item = toolbar.data.get(itemId);
		return item ? new ToolbarItemWrapper({item: item, toolbar: this}) : null;
	},

	showItem: function(itemId) {
		var item = this.hiddenItems[itemId];
		if (!item) {
			return;
		}

		var toolbar = this._toolbar;
		toolbar.data.get(itemId).visible = true;

		var itemsContainer = toolbar[item.containerName];
		itemsContainer.splice(item.position, 0, item.item.id);

		toolbar[item.containerName] = itemsContainer;
	},

	hideItem: function(itemId) {
		let item = this.getItem(itemId);
		item = item ? item._item_Experimental : null;
		if (!item) {
			return;
		}

		var id = item.id;
		item.visible = false;
		var toolbar = this._toolbar;

		var containerName = 'container';
		var itemsContainer = toolbar.container;
		var itemIndex = itemsContainer.indexOf(id);
		if (itemIndex === -1) {
			containerName = 'rightContainer';
			itemsContainer = toolbar.rightContainer;
			itemIndex = itemsContainer.indexOf(id);
		}
		if (itemIndex === -1) {
			return;
		}
		this.hiddenItems[id] = {
			item: item,
			position: itemIndex,
			containerName: containerName
		};

		itemsContainer.splice(itemIndex, 1);
		toolbar[containerName] = itemsContainer;
	},

	getActiveToolbar: function() {
		return this;
	},

	disable: function() {
		return this.setEnabled_Experimental(false);
	},

	enable: function() {
		return this.setEnabled_Experimental(true);
	},

	getButtonXY: function(itemId) {
		var item = this.getItem(itemId);
		if (!item) {
			return '';
		}
		var b = item.GetBounds();
		return (b.left + b.width / 2) + ',' + (b.top + b.height / 2);
	},

	getButtonId: function(label) {
		var arr = this.getItemIdsAsArr_Experimental();
		for (var i = 0; i < arr.length; i++) {
			var itemLabel = this.getButtonLabelById(arr[i]);
			if (itemLabel === label) {
				var item = this.getItem(arr[i]);
				return item.getId();
			}
		}
	},

	isButtonEnabled: function(itemId) {
		var item = this.getItem(itemId);
		return item === null ? false : item.getEnabled();
	},

	getButtonLabelById: function(itemId) {
		var item = this.getItem(itemId);
		return item ? item._item_Experimental.label : '';
	},

	isButtonVisible: function(itemId) {
		return this.isItemVisible_Experimental(itemId);
	},

	getButtons: function(separator) {
		return this.getItemIds_Experimental(separator);
	},

	getItemSize: function(itemId) {
		var item = document.getElementById(itemId);
		if (item && this._toolbar) {
			while (item.parentNode && item.parentNode != this._toolbar.domNode) {
				item = item.parentNode;
			}
			return item.offsetWidth + ',' + item.offsetHeight;
		}
		return false;
	},

	getCurrentToolBarDomNode_Experimental: function() {
		return this._toolbar.dom;
	},

	refreshToolbar_Experimental: function() {
		if (this._toolbar) {
			this._toolbar.render();
		}
	},

	setEnabled_Experimental: function(isEnabled) {
		var tbi;
		var i;
		var arr = this.getItemIdsAsArr_Experimental();
		for (i in arr) {
			tbi = this.getItem(arr[i]);
			if (tbi) {
				tbi.setEnabled(isEnabled);
			}
		}
	},

	isItemVisible_Experimental: function(id) {
		var element = this.getItem(id);
		return (element && element._item_Experimental) ? element._item_Experimental.visible : false;
	},

	getItemIdsAsArr_Experimental: function() {
		var currentToolbar = this._toolbar;
		var idList = [];

		if (currentToolbar) {
			var dropDownItems = currentToolbar._dropDownToolBar ? currentToolbar._dropDownToolBar.getChildren() : [];
			var toolbarItems = currentToolbar.data;

			toolbarItems.forEach(function(item) {
				idList.push(item.id);
			});
		}

		return idList;
	},

	getItemIds_Experimental: function(separator) {
		return this.getItemIdsAsArr_Experimental().join(separator);
	}
};

/** Aras\Client\Controls\Public\ToolbarItemWrapper.js **/
function ToolbarItemWrapper(args) {
	if (typeof (arasDocumentationHelper) !== 'undefined') {
		arasDocumentationHelper.registerProperties({});
		arasDocumentationHelper.registerEvents('');
		return;
	}

	const item = args.item;
	const toolbar = args.toolbar;
	this._widget = {
		get domNode() {
			const toolbarNode = toolbar._toolbar.dom;
			return toolbarNode.querySelector('span[data-id="' + item.id + '"]');
		},
		get: function(prop) {
			if (prop === 'style') {
				return this.domNode.style.cssText;
			}

			return item[prop];
		},
		set: function(prop, value) {
			if (prop === 'style') {
				this.domNode.style.cssText += value;
			} else {
				item[prop] = value;
			}
		},
		setPlaceholder: function() {},
	};
	this._item_Experimental = item;
	this._toolbar = toolbar;
	for (var method in this) {
		if (typeof this[method] === 'function') {
			var methodName = method.substr(0, 1).toUpperCase() + method.substr(1);
			this[methodName] = this[method];
		}
	}
}

ToolbarItemWrapper.prototype = {
	_item_Experimental: null,

	getId: function() {
		return this._item_Experimental.id;
	},

	getState: function() {
		if ('toggleButton' == this._item_Experimental.type || 'checkedMenuItem' == this._item_Experimental.type ||
			'radioButtonMenuItem' == this._item_Experimental.type) {
			return this._item_Experimental.get.checked;
		}
	},

	setState: function(isPushed) {
		if ('toggleButton' == this._item_Experimental.type || 'checkedMenuItem' == this._item_Experimental.type ||
			'radioButtonMenuItem' == this._item_Experimental.type) {
			this._item_Experimental.checked = isPushed;
		}
	},

	setEnabled: function(bool) {
		if (this._item_Experimental.disabled !== bool) {
			return;
		}
		this._item_Experimental.disabled = !bool;
		var itemId = this._item_Experimental.id;
		var toolbarComponent = this._toolbar._toolbar;
		toolbarComponent.data.set(itemId, Object.assign({}, this._item_Experimental));
		this._toolbar.refreshToolbar_Experimental();
	},

	getEnabled: function() {
		return !this._item_Experimental.disabled;
	},

	setItemVisible: function(itemId, isVisible) {
		isVisible = isVisible === undefined || isVisible;
		if ('dijit.form.DropDownButton' === this._item_Experimental.declaredClass) {
			var menu = this._item_Experimental.get('dropDown');
			var items = menu.getChildren();
			for (var i = 0; i < items.length; i += 1) {
				if (items[i].popup !== undefined) {
					var popupItems = items[i].popup.getChildren();
					for (var j = 0; j < popupItems.length; j += 1) {
						if (itemId == popupItems[j].id) {
							popupItems[j].domNode.style.display = isVisible ? '' : 'none';
						}
					}
				}
				if (itemId == items[i].id) {
					items[i].domNode.style.display = isVisible ? '' : 'none';
				}
			}
		}
	},

	getSelectedIndex: function() {
		if ('select' === this._item_Experimental.type || 'htmlSelector' === this._item_Experimental.type) {
			var options = this._item_Experimental.options;
			var selectedId = this._item_Experimental.value;
			var index = -1;
			for (var i = 0; i < options.length; i++) {
				if (options[i].value == selectedId) {
					index = i;
					break;
				}
			}
			return index;
		}
	},

	removeAll: function() {
		var toolbarComponent = this._toolbar._toolbar;
		if ('select' === this._item_Experimental.type || 'htmlSelector' === this._item_Experimental.type) {
			this._item_Experimental.options = [];
			toolbarComponent.render();
		} else if ('dropdownButton' === this._item_Experimental.type) {
			this._item_Experimental.options = [];
			var itemId = this._item_Experimental.id;
			toolbarComponent.data.set(itemId, Object.assign({}, this._item_Experimental));
			toolbarComponent.render();
		}
	},

	addSeparator: function() {
		if ('select' === this._item_Experimental.type || 'htmlSelector' === this._item_Experimental.type) {
			this._item_Experimental.options.push({type: 'separator'});
		}
	},

	add: function(id, label, checked) {
		var toolbarComponent = this._toolbar._toolbar;
		const itemId = this._item_Experimental.id;
		if ('select' === this._item_Experimental.type || 'htmlSelector' === this._item_Experimental.type) {
			const newItem = Object.assign({}, this._item_Experimental);
			newItem.options = newItem.options.concat([{value: id, label: label}]);
			toolbarComponent.data.set(itemId, newItem);
			this._item_Experimental = newItem;
			toolbarComponent.render();
		} else if ('dropdownButton' === this._item_Experimental.type) {
			this._item_Experimental.options.push({value: id, label: label});
			toolbarComponent.data.set(itemId, Object.assign({}, this._item_Experimental));
			toolbarComponent.render();
		}
	},

	getSelectedItem: function() {
		if ('select' === this._item_Experimental.type || 'htmlSelector' === this._item_Experimental.type) {
			return this._item_Experimental.value;
		}
	},

	setSelected: function(id) {
		if ('select' == this._item_Experimental.type) {
			this._item_Experimental.value = id;
			var itemId = this._item_Experimental.id;
			var toolbarComponent = this._toolbar._toolbar;
			toolbarComponent.data.set(itemId, Object.assign({}, this._item_Experimental));
			this._toolbar.refreshToolbar_Experimental();
		}
	},

	getItem: function(id) {
		if ('select' == this._item_Experimental.type || 'htmlSelector' === this._item_Experimental.type) {
			return this._item_Experimental.options[id].label;
		} else if ('dijit.form.DropDownButton' === this._item_Experimental.declaredClass) {
			var menu = this._item_Experimental.get('dropDown');
			var menuChilds = menu.getChildren();
			var childItem;
			var i;

			for (i = 0; i < menuChilds.length; i++) {
				childItem = menuChilds[i];

				if (childItem.id == id) {
					return new Aras.Client.Controls.Public.ToolbarItem({item: childItem});
				}
			}
		}
	},

	remove: function(name) {
		if ('select' == this._item_Experimental.type) {
			var options = this._item_Experimental.options;
			var index = options.findIndex(function(option) {
				return name === option.value;
			});
			if (index === -1) {
				return;
			}
			options.splice(index, 1);
			if (name === this._item_Experimental.value) {
				this._item_Experimental.value = options.length ? options[0].value : '';
			}
		}
	},

	getItemCount: function() {
		if ('select' == this._item_Experimental.type || 'htmlSelector' === this._item_Experimental.type ||
			'dropdownButton' === this._item_Experimental.type) {
			return this._item_Experimental.options.length;
		}
	},

	setText: function(value) {
		this._item_Experimental.value = value;
		var itemId = this._item_Experimental.id;
		var toolbarComponent = this._toolbar._toolbar;
		toolbarComponent.data.set(itemId, Object.assign({}, this._item_Experimental));
		this._toolbar.refreshToolbar_Experimental();
	},

	getText: function() {
		return this._item_Experimental.value;
	},

	setLabel: function(value, position) {
		var itemWidget = this._item_Experimental;
		if ('Aras.Client.Controls.Experimental._toolBar.AdvancedTextBox' === itemWidget.declaredClass) {
			if (position === 'right') {
				itemWidget.setLabelAfter(value);
			} else if (position === 'left') {
				itemWidget.setLabelBefore(value);
			}
		} else {
			var textLabelNode = itemWidget.textLabel;
			if (textLabelNode) {
				textLabelNode.innerHTML = value;
			} else {
				var topWindow = window.TopWindowHelper.getMostTopWindowWithAras();
				var errorName = topWindow.aras.getResource('', 'toolbar.set_label_method_unsupported');
				throw new Error(1, errorName);
			}
		}
	},

	getBounds: function() {
		var item = this._item_Experimental.domNode;
		var bounds = {
			top: item.offsetTop - item.parentElement.offsetTop,
			left: item.offsetLeft - item.parentElement.offsetLeft,
			width: item.offsetWidth,
			height: item.offsetHeight
		};
		return bounds;
	},

	enable: function() {
		this.setEnabled(true);
	},

	disable: function() {
		this.setEnabled(false);
	}
};

/** ..\Modules\aras.innovator.ExtendedClassification\scripts\xClassSearch\CheckboxState.js **/
function CheckboxState(value, labelkey, key, generateAmlFunction, markerCheckboxState) {
	this.value = value;
	this.class = key;
	this.getAml = generateAmlFunction || function() {};
	this.markerCheckboxState = markerCheckboxState;
	Object.defineProperty(this, 'label', {
		get: function() {
			if (!this._label) {
				this._label = aras.getResource('../Modules/aras.innovator.ExtendedClassification', labelkey);
			}
			return this._label;
		}
	});
}

CheckboxState.prototype.getXClassesIdByMarkerState = function(queryNode, logicState, itemTypeName, relItemTypeName) {
	const ids = [];
	if (!queryNode || !queryNode.xml || !this.markerCheckboxState) {
		return ids;
	}
	const xPath = this.markerCheckboxState(logicState, itemTypeName, relItemTypeName);
	const idNodes = ArasModules.xml.selectNodes(queryNode, xPath);

	idNodes.forEach(function(idNode) {
		ids.push(idNode.text);
	});
	return ids;
};

CheckboxState.prototype.getTagNameFromXPathNode = function(xPathNode) {
	const startXpathAxis = xPathNode.lastIndexOf(':');
	if (startXpathAxis > -1) {
		xPathNode = xPathNode.slice(startXpathAxis + 1, xPathNode.length);
	}
	const startXPathParameters = xPathNode.indexOf('[');
	if (startXPathParameters > -1) {
		xPathNode = xPathNode.slice(0, startXPathParameters);
	}
	return xPathNode;
};

CheckboxState.prototype.getTagAttributesFromXPathNode = function(xPathNode) {
	const startParameters = xPathNode.indexOf('[');
	const endParameters = xPathNode.indexOf(']');
	let attributesObj = {};
	if (startParameters > -1 && endParameters > -1) {
		let attributes = xPathNode.slice(startParameters + 1, endParameters).replace(/@/g, '').replace(/"/g, '');
		attributes = attributes.split(' and ');
		attributes.forEach(function(attributeString) {
			const atributeParam = attributeString.split('=');
			attributesObj[atributeParam[0]] = atributeParam[1];
		});
	}
	return attributesObj;
};

CheckboxState.prototype.createElementByXPathNode = function(parent, xPathNode) {
	const tagName = this.getTagNameFromXPathNode(xPathNode);
	const attributes = this.getTagAttributesFromXPathNode(xPathNode);
	const element = aras.createXmlElement(tagName, parent);
	Object.keys(attributes).forEach(function(nameAttribute) {
		element.setAttribute(nameAttribute, attributes[nameAttribute]);
	});
	return element;
};

CheckboxState.prototype.insertToNode = function(xPathToInsertTargetNode, targetNode, nodeToInsert) {
	let xPathNodes = xPathToInsertTargetNode.split('/');
	let xPathToCurrentNode = '';
	let nodeToInsertTargetNode = nodeToInsert;
	xPathNodes.forEach(function(xPathNode) {
		if (xPathNode.length > 0) {
			xPathToCurrentNode += xPathNode;
			const node = nodeToInsert.selectSingleNode(xPathToCurrentNode);
			if (!node) {
				nodeToInsertTargetNode = this.createElementByXPathNode(nodeToInsertTargetNode, xPathNode);
			} else {
				nodeToInsertTargetNode = node;
			}
		}
		xPathToCurrentNode += '/';
	}, this);
	nodeToInsertTargetNode.appendChild(targetNode);
};

CheckboxState.prototype.getMarkerCheckboxStateAdditionalPath = function(itemTypeName, relItemTypeName) {
	if (relItemTypeName && relItemTypeName !== itemTypeName) {
		return '/related_id/Item[@type="' + itemTypeName + '" and @action="get"]/';
	}
	return '';
};

/** ..\Modules\aras.innovator.ExtendedClassification\scripts\xClassSearch\XClassSearchCheckbox.js **/
(function() {
	const pathToResource = '../Modules/aras.innovator.ExtendedClassification/';

	function XClassSearchCheckbox(state, xClassHaveChild) {
		this.state = state || XClassSearchCheckbox.States.STATE_DEFAULT;
		this.generateOrderStates(!!xClassHaveChild);
	}

	XClassSearchCheckbox.prototype = {
		generateOrderStates: function(xClassHaveChild, conditionIsAND) {
			if (xClassHaveChild && !!conditionIsAND) {
				this.orderStates = [
					XClassSearchCheckbox.States.STATE_CHECKED,
					XClassSearchCheckbox.States.STATE_HARD_CHECKED,
					XClassSearchCheckbox.States.STATE_UNCHECKED,
					XClassSearchCheckbox.States.STATE_HARD_UNCHECKED,
					XClassSearchCheckbox.States.STATE_DEFAULT
				];
			} else {
				this.orderStates = [
					XClassSearchCheckbox.States.STATE_CHECKED,
					XClassSearchCheckbox.States.STATE_UNCHECKED,
					XClassSearchCheckbox.States.STATE_DEFAULT
				];
				if ((!xClassHaveChild && !!conditionIsAND &&
						(this.state === XClassSearchCheckbox.States.STATE_HARD_CHECKED ||
							this.state === XClassSearchCheckbox.States.STATE_HARD_UNCHECKED)) ||
					(!conditionIsAND &&
						(this.state === XClassSearchCheckbox.States.STATE_SOFT_CHECKED ||
							this.state === XClassSearchCheckbox.States.STATE_SOFT_UNCHECKED ||
							this.state === XClassSearchCheckbox.States.STATE_HARD_CHECKED ||
							this.state === XClassSearchCheckbox.States.STATE_HARD_UNCHECKED))) {
					this.state = XClassSearchCheckbox.States.STATE_DEFAULT;
				}
			}
		},
		nextState: function() {
			let index = this.orderStates.indexOf(this.state);
			if (index === -1 || index === this.orderStates.length - 1) {
				index = 0;
			} else {
				index++;
			}
			this.state = this.orderStates[index];
		},
		get formatter() {
			return {
				tag: 'label',
				className: 'aras-form-boolean ' + this.state.class,
				children: [
					{
						tag: 'input',
						attrs: {
							type: 'checkbox',
							checked: this.state.value
						}
					},
					{
						tag: 'span'
					}
				]
			};
		}
	};

	XClassSearchCheckbox.States = {
		STATE_DEFAULT: new CheckboxState(true, 'xClassSearchControl.checkbox_label.default', 'mixed'),
		STATE_CHECKED: new CheckboxState(true, 'xClassSearchControl.checkbox_label.checked', 'checked',
			function(insertNode, id, itemTypeName, logicState) {
				let pathToInsertNode;
				const targetNodeXmlDoc = aras.createXMLDocument();
				if (logicState === XClassSearchCheckbox.LogicStates.AND) {
					pathToInsertNode = 'self::' + logicState.tagName + '/Relationships';
					targetNodeXmlDoc.loadXML('<Item type="' + itemTypeName + '_xClass" action="get">' +
						'<related_id>' + id + '</related_id>' +
						'</Item>');
				} else if (logicState === XClassSearchCheckbox.LogicStates.OR) {
					pathToInsertNode = 'self::' + logicState.tagName + '/Relationships/' +
						'Item[@type="' + itemTypeName + '_xClass" and @action="get"]/OR';
					targetNodeXmlDoc.loadXML('<related_id>' + id + '</related_id>');
				}
				if (pathToInsertNode) {
					this.insertToNode(pathToInsertNode, targetNodeXmlDoc.documentElement, insertNode);
					return true;
				}
				return false;
			},
			function(logicState, itemTypeName, relItemTypeName) {
				const additionalPath = this.getMarkerCheckboxStateAdditionalPath(itemTypeName, relItemTypeName);
				if (logicState === XClassSearchCheckbox.LogicStates.AND) {
					return '.' + additionalPath + '/Relationships/' +
						'Item[@type="' + itemTypeName + '_xClass" and @action="get"]/related_id';
				}
				if (logicState === XClassSearchCheckbox.LogicStates.OR) {
					return '.' + additionalPath + '/Relationships/' +
						'Item[@type="' + itemTypeName + '_xClass" and @action="get"]/OR/related_id';
				}
			}
		),
		STATE_HARD_CHECKED: new CheckboxState(true, 'xClassSearchControl.checkbox_label.hard_checked', 'hard_checked',
			function(insertNode, id, itemTypeName, logicState) {
				const targetNodeXmlDoc = aras.createXMLDocument();
				const pathToInsertNode = 'self::' + logicState.tagName + '/Relationships';
				targetNodeXmlDoc.loadXML('<Item type="' + itemTypeName + '_xClass" action="get" select="related_id(id)">' +
					'<related_id>' +
						'<Item type="xClass" action="getXClassAndAllDescendants" select="id">' +
							'<id>' + id + '</id>' +
						'</Item>' +
					'</related_id>' +
				'</Item>');
				this.insertToNode(pathToInsertNode, targetNodeXmlDoc.documentElement, insertNode);
				return true;
			},
			function(logicState, itemTypeName, relItemTypeName) {
				const additionalPath = this.getMarkerCheckboxStateAdditionalPath(itemTypeName, relItemTypeName);
				return '.' + additionalPath + '/Relationships/' +
					'Item[@type="' + itemTypeName + '_xClass" and @action="get"]/related_id/Item[@type="xClass" and @action="getXClassAndAllDescendants"]/id';
			}
		),
		STATE_SOFT_CHECKED: new CheckboxState(true, '', 'soft_checked'),
		STATE_UNCHECKED: new CheckboxState(false, 'xClassSearchControl.checkbox_label.unchecked', 'unchecked',
			function(insertNode, id, itemTypeName, logicState) {
				let pathToInsertNode;
				const targetNodeXmlDoc = aras.createXMLDocument();
				if (logicState === XClassSearchCheckbox.LogicStates.AND) {
					pathToInsertNode = 'self::' + logicState.tagName + '/NOT/Relationships';
					targetNodeXmlDoc.loadXML('<Item type="' + itemTypeName + '_xClass" action="get">' +
						'<related_id>' + id + '</related_id>' +
						'</Item>');
				} else if (logicState === XClassSearchCheckbox.LogicStates.OR) {
					pathToInsertNode = 'self::' + logicState.tagName + '/NOT/Relationships/' +
						'Item[@type="' + itemTypeName + '_xClass" and @action="get"]/OR';
					targetNodeXmlDoc.loadXML('<related_id>' + id + '</related_id>');
				}
				if (pathToInsertNode) {
					this.insertToNode(pathToInsertNode, targetNodeXmlDoc.documentElement, insertNode);
					return true;
				}
				return false;
			},
			function(logicState, itemTypeName, relItemTypeName) {
				const additionalPath = this.getMarkerCheckboxStateAdditionalPath(itemTypeName, relItemTypeName);
				if (logicState === XClassSearchCheckbox.LogicStates.AND) {
					return '.' + additionalPath + '/NOT/Relationships/' +
						'Item[@type="' + itemTypeName + '_xClass" and @action="get"]/related_id';
				}
				if (logicState === XClassSearchCheckbox.LogicStates.OR) {
					return '.' + additionalPath + '/NOT/Relationships/' +
						'Item[@type="' + itemTypeName + '_xClass" and @action="get"]/OR/related_id';
				}
			}
		),
		STATE_HARD_UNCHECKED: new CheckboxState(false, 'xClassSearchControl.checkbox_label.hard_unchecked', 'hard_unchecked',
			function(insertNode, id, itemTypeName, logicState) {
				const pathToInsertNode = 'self::' + logicState.tagName + '/NOT/Relationships/Item[@type="' +
					itemTypeName + '_xClass" and @action="get" and @select="related_id(id)"]' +
					'/related_id/Item[@type="xClass" and @action="getXClassAndAllDescendants" and @select="id"]/OR';
				const targetNodeXmlDoc = aras.createXMLDocument();
				targetNodeXmlDoc.loadXML('<id>' + id + '</id>');
				this.insertToNode(pathToInsertNode, targetNodeXmlDoc.documentElement, insertNode);
				return true;
			},
			function(logicState, itemTypeName, relItemTypeName) {
				const additionalPath = this.getMarkerCheckboxStateAdditionalPath(itemTypeName, relItemTypeName);
				return '.' + additionalPath + '/NOT/Relationships/Item[@type="' + itemTypeName + '_xClass" and @action="get" and @select="related_id(id)"]' +
					'/related_id/Item[@type="xClass" and @action="getXClassAndAllDescendants" and @select="id"]/OR/id';
			}
		),
		STATE_SOFT_UNCHECKED: new CheckboxState(false, '', 'soft_unchecked'),
		getStateByClassName: function(value) {
			const checkbox = Object.keys(this).find(function(checkbox) {
				return this[checkbox].class === value;
			}, this);
			return this[checkbox];
		}
	};

	Object.defineProperty(XClassSearchCheckbox.States, 'getStateByClassName', {enumerable: false});

	XClassSearchCheckbox.LogicStates = {
		AND: {
			class: 'condition-and',
			tagName: 'AND'
		},
		OR: {
			class: 'condition-or',
			tagName: 'OR'
		}
	};

	window.XClassSearchCheckbox = XClassSearchCheckbox;
})();

/** ..\Modules\aras.innovator.ExtendedClassification\scripts\xClassSearch\XClass.js **/
function XClass(id, name, xClassTreeId, parentId) {
	this.id = id;
	this.name = name;
	this.xClassTreeId = xClassTreeId;
	this.parentId = parentId;
	this.children = [];
	this.isFiltered = false;
	this.checkbox = new XClassSearchCheckbox();
	this.isRelationship = false;
}

XClass.prototype = {
	constructor: XClass,
	addChildXClass: function(xClass, logicState) {
		this.children.push(xClass);
		if (this.children.length === 1) {
			this.checkbox.generateOrderStates(true, logicState === XClassSearchCheckbox.LogicStates.AND);
		}
	},
	nextStateCheckbox: function() {
		const previousState = this.checkbox.state;
		this.checkbox.nextState();
		this.updateChildrenState(this.checkbox.state, previousState);
	},
	setCheckboxState: function(state) {
		let previousState;
		if (state !== this.checkbox.state) {
			previousState = this.checkbox.state;
			this.checkbox.state = state;
		}
		this.updateChildrenState(state, previousState);
	},
	updateChildrenState: function(currentState, previousState) {
		switch (previousState) {
			case XClassSearchCheckbox.States.STATE_HARD_CHECKED:
			case XClassSearchCheckbox.States.STATE_SOFT_CHECKED:
			case XClassSearchCheckbox.States.STATE_HARD_UNCHECKED:
			case XClassSearchCheckbox.States.STATE_SOFT_UNCHECKED:
				this.setChildrenState(XClassSearchCheckbox.States.STATE_DEFAULT);
				break;
		}
		switch (currentState) {
			case XClassSearchCheckbox.States.STATE_HARD_CHECKED:
			case XClassSearchCheckbox.States.STATE_SOFT_CHECKED:
				this.setChildrenState(XClassSearchCheckbox.States.STATE_SOFT_CHECKED);
				break;
			case XClassSearchCheckbox.States.STATE_HARD_UNCHECKED:
			case XClassSearchCheckbox.States.STATE_SOFT_UNCHECKED:
				this.setChildrenState(XClassSearchCheckbox.States.STATE_SOFT_UNCHECKED);
				break;
		}
	},
	setChildrenState: function(state) {
		this.children.forEach(function(xClass) {
			xClass.setCheckboxState(state);
		});
	},
	toogleFilter: function() {
		this.isFiltered = !this.isFiltered;
		xClassSearchWrapper.updateColumnSelection();
	},
	find: function(searchText) {
		this.clearSearchData();
		let answer = false;
		if (this.name.indexOf(searchText) > -1) {
			this.searchText = searchText;
			answer = true;
		}
		return answer;
	},
	clearSearchData: function() {
		this.searchText = '';
	},
	getFormatterData: function(isFilteredMode) {
		const filterFormater = {
			tag: 'label',
			className: 'filter' + (this.isFiltered ? ' apply-filter' : ''),
			children: [
				{
					tag: 'input',
					attrs: {
						type: 'checkbox',
						checked: this.isFiltered
					}
				},
				{
					tag: 'span'
				}
			]
		};
		const titleFormatter = {
			tag: 'div',
			className: 'checkbox-title'
		};
		if (this.searchText) {
			const indexStartFoundText = this.name.indexOf(this.searchText);
			const indexEndFoundText = indexStartFoundText + this.searchText.length;
			titleFormatter.children = [
				this.name.slice(0, indexStartFoundText),
				{
					tag: 'mark',
					children: [this.name.slice(indexStartFoundText, indexEndFoundText)]
				},
				this.name.slice(indexEndFoundText)
			];
		} else {
			titleFormatter.children = [this.name];
		}
		if (this.level > 1 && !isFilteredMode) {
			titleFormatter.children.unshift({
				tag: 'span',
				className: 'icon selected-value-img'
			});
			titleFormatter.style = {'margin-left': 15 * (this.level - 1) + 'px'};
		}
		return {
			className: 'aras-grid-row-cell_boolean',
			children: [
				{
					tag: 'div',
					children: [
						filterFormater,
						titleFormatter
					]
				},
				this.checkbox.formatter
			]
		};
	},
};

/** ..\Modules\aras.innovator.ExtendedClassification\scripts\xClassSearch\xClassSearchControl.js **/
(function() {
	const pathToResource = '../Modules/aras.innovator.ExtendedClassification/';
	const infernoFlags = ArasModules.utils.infernoFlags;
	const relationshipIdPrefix = 'R_';
	const relationshipNamePrefix = '[R]';

	const AnyXClass = new XClass('any_classification');
	Object.defineProperty(AnyXClass, 'name', {
		get: function() {
			if (!this._name) {
				this._name = aras.getResource(pathToResource, 'xClassSearchControl.xClass.any_classification');
			}
			return this._name;
		}
	});
	AnyXClass.checkbox.orderStates = [
		XClassSearchCheckbox.States.STATE_DEFAULT,
		XClassSearchCheckbox.States.STATE_HARD_CHECKED,
		XClassSearchCheckbox.States.STATE_HARD_UNCHECKED
	];
	Object.assign(AnyXClass, {
		setChildrenState: function(state) {
			xClassSearchControl.allXClasses.forEach(function(xClass) {
				xClass.setCheckboxState(state);
			}.bind(this));
		},
		getAml: function(itemTypeName, relationshipTypeName, currentQueryItem) {
			let generalQuery;
			if (this.checkbox.state === XClassSearchCheckbox.States.STATE_HARD_CHECKED) {
				generalQuery = '<OR xClassSearchCriteria="1">';
				if (relationshipTypeName && xClassSearchControl.relationshipXClasses.size > 0) {
					generalQuery +=
'<Relationships>' +
	'<Item type="' + relationshipTypeName + '_xClass" action="get">' +
		'<related_id condition="is not null"/>' +
	'</Item>' +
'</Relationships>';
				}
				if (xClassSearchControl.xClasses.size > 0) {
					const query =
'<Relationships>' +
	'<Item type="' + itemTypeName + '_xClass" action="get">' +
		'<related_id condition="is not null"/>' +
	'</Item>' +
'</Relationships>';
					if (relationshipTypeName) {
						generalQuery +=
'<related_id>' +
	'<Item type="' + itemTypeName + '" action="get">' +
		'<AND>' + query + '</AND>' +
	'</Item>' +
'</related_id>';
					} else {
						generalQuery += query;
					}
				}
				generalQuery += '</OR>';
			} else if (this.checkbox.state === XClassSearchCheckbox.States.STATE_HARD_UNCHECKED) {
				generalQuery = '<NOT xClassSearchCriteria="1"><OR>';
				if (relationshipTypeName && xClassSearchControl.relationshipXClasses.size > 0) {
					generalQuery +=
'<id condition="in" by="source_id">' +
	'<Item type="' + relationshipTypeName + '_xClass" action="get">' +
		'<related_id condition="is not null" />' +
	'</Item>' +
'</id>';
				}
				if (xClassSearchControl.xClasses.size > 0) {
					const query =
'<Item type="' + itemTypeName + '_xClass" action="get">' +
	'<related_id condition="is not null" />' +
'</Item>';
					if (relationshipTypeName) {
						generalQuery +=
'<related_id condition="in" by="source_id">' +
	query +
'</related_id>';
					} else {
						generalQuery +=
'<id condition="in" by="source_id">' +
	query +
'</id>';
					}
				}

				generalQuery += '</OR></NOT>';
			}
			if (generalQuery) {
				const queryXmlDoc = aras.createXMLDocument();
				queryXmlDoc.loadXML(generalQuery);
				currentQueryItem.appendChild(queryXmlDoc.documentElement);
				return currentQueryItem.xml;
			}
		},
		parseItemAml: function(query, itemTypeName, relationshipItemTypeName) {
			const queryElement = aras.createXMLDocument();
			queryElement.loadXML(query.xml);
			let answer = false;
			let checkedXPath = '//OR[@xClassSearchCriteria="1"]/Relationships/Item/related_id[@condition="is not null"]';
			let uncheckedXPath = '//NOT[@xClassSearchCriteria="1"]/OR/id[@condition="in" and @by="source_id"]/' +
				'Item[contains(@type,"_xClass")]/related_id[@condition="is not null"]';

			if (relationshipItemTypeName) {
				checkedXPath += '|//OR[@xClassSearchCriteria="1"]/related_id/Item[@type="' + itemTypeName +
					'"]/AND/Relationships/Item/related_id[@condition="is not null"]';
				uncheckedXPath = '//NOT[@xClassSearchCriteria="1"]/OR/*[(local-name() = "id" or local-name() = "related_id")' +
					' and @condition="in" and @by="source_id"]/Item[contains(@type,"_xClass")]/related_id[@condition="is not null"]';
			}

			if (queryElement.selectSingleNode(checkedXPath)) {
				answer = true;
				this.setCheckboxState(XClassSearchCheckbox.States.STATE_HARD_CHECKED);
			} else if (queryElement.selectSingleNode(uncheckedXPath)) {
				answer = true;
				this.setCheckboxState(XClassSearchCheckbox.States.STATE_HARD_UNCHECKED);
			} else {
				this.setCheckboxState(XClassSearchCheckbox.States.STATE_DEFAULT);
			}
			return answer;
		},
		getFormatterData: function() {
			const titleFormatter = {
				tag: 'div',
				className: 'checkbox-title',
				children: [this.name],
				style: {
					'margin-left': '25px'
				}
			};
			return {
				className: 'aras-grid-row-cell_boolean',
				children: [
					{
						tag: 'div',
						children: [
							titleFormatter
						]
					},
					this.checkbox.formatter
				]
			};
		}
	});

	const xClassSearchControl = {
		xClasses: new Map(),
		relationshipXClasses: new Map(),
		get allXClasses() {
			const allXClasses = new Map();
			this.xClasses.forEach(function(value, key) {
				allXClasses.set(key, value);
			});
			this.relationshipXClasses.forEach(function(xClass, id) {
				allXClasses.set(id, xClass);
			});
			return allXClasses;
		},
		init: function(xClassTrees, relationshipXClassTrees) {
			const combineStateOldXClassWithNew = function() {
				const oldXClasses = this.allXClasses;
				return function() {
					if (!oldXClasses || !this.allXClasses || oldXClasses.size === 0 || this.allXClasses.size === 0) {
						return;
					}
					oldXClasses.forEach(function(oldXClass, id) {
						const xClass = this.allXClasses.get(id);
						if (xClass) {
							xClass.isFiltered = oldXClass.isFiltered;
						}
					}.bind(this));
				}.bind(this);
			}.bind(this)();
			this.xClasses = this.parseXClasses(xClassTrees);
			if (relationshipXClassTrees) {
				const relationshipXClasses = this.parseXClasses(relationshipXClassTrees);
				relationshipXClasses.forEach(function(xClass) {
					const id = relationshipIdPrefix + xClass.id;
					xClass.name = relationshipNamePrefix + ' ' + xClass.name;
					xClass.isRelationship = true;
					this.relationshipXClasses.set(id, xClass);
				}.bind(this));
			}
			combineStateOldXClassWithNew();
			this.initGridData(this.allXClasses);
		},
		setSearchFilter: function(filterState) {
			this.clearFoundXClasses();
			if (filterState) {
				this.visibleXClass = filterState.filter();
				this.currentSearchFilter = filterState;
				if (filterState === xClassSearchFilters.ALL) {
					this.isFilteredMode = false;
				} else {
					this.isFilteredMode = true;
				}
			}
		},
		initGrid: function(container) {
			this.grid = new Grid(container, {multiSelect: false});
			this.grid.getCellType = function() {
				return 'xClass';
			};
			Grid.formatters.xClass = function(headId, rowId, value, grid) {
				const xClass = grid.rows.get(rowId);
				return xClass.getFormatterData(xClassSearchControl.isFilteredMode);
			};
			this.grid.on('click', function(rowId, event) {
				if (event.target.tagName !== 'INPUT') {
					const xClass = this.grid.rows.get(rowId);
					if (event.target.closest('.filter') && this.canClickableFilters) {
						const filterBlock = event.target.closest('.filter');
						xClass.toogleFilter();
						if (xClass.isFiltered) {
							filterBlock.classList.add('apply-filter');
						} else {
							filterBlock.classList.remove('apply-filter');
						}
					} else if (event.target.closest('.aras-form-boolean') &&
						this.supportXClassSearch &&
						xClass.checkbox.state !== XClassSearchCheckbox.States.STATE_SOFT_CHECKED &&
						xClass.checkbox.state !== XClassSearchCheckbox.States.STATE_SOFT_UNCHECKED) {
						xClass.nextStateCheckbox();
					}
					this.grid.render();
				}
			}.bind(this), 'row');

			const contextMenu = new ArasModules.ContextMenu(xClassSearchWrapper.node);
			contextMenu.on('click', function(menuItemId, e, rowId) {
				const state = XClassSearchCheckbox.States.getStateByClassName(menuItemId);
				const xClass = this.grid.rows.get(rowId);
				xClass.setCheckboxState(state);
				this.grid.render();
				columnSelectionControl.node.parentElement.focus();
			}.bind(this));

			this.grid.on('contextmenu', function(rowId, event) {
				if (event.target.closest('.aras-form-boolean') && this.supportXClassSearch) {
					event.preventDefault();
					const xClass = this.grid.rows.get(rowId);
					if (xClass.checkbox.state == XClassSearchCheckbox.States.STATE_SOFT_CHECKED ||
						xClass.checkbox.state == XClassSearchCheckbox.States.STATE_SOFT_UNCHECKED) {
						return false;
					}
					const data = {};
					xClass.checkbox.orderStates.forEach(function(state) {
						if (xClass.checkbox.state != state) {
							const span = Inferno.createVNode(Inferno.getFlagsForElementVnode('span'), 'span', null, null,
							infernoFlags.hasInvalidChildren, {
								onClick: function(e) {
									e.target.parentElement.click();
								}
							});
							data[state.class] = {
								label: [span, state.label]
							};
						}
					});
					contextMenu.applyData(data);
					const clickPosition = {top: event.pageY, left: event.pageX};
					const docSize = {
						width: document.documentElement.clientWidth,
						height: document.documentElement.clientHeight,
						scrollLeft: document.documentElement.scrollLeft,
						scrollTop: document.documentElement.scrollTop
					};
					contextMenu.dom.style.visibility = 'hidden';
					return contextMenu.show({x: 0, y: 0}, rowId).then(function() {
						const menuRect = contextMenu.dom.getBoundingClientRect();
						const parentNodeRect = xClassSearchWrapper.node.parentNode.getBoundingClientRect();

						let x = clickPosition.left;
						if (x + menuRect.width > docSize.width + docSize.scrollLeft) {
							x = clickPosition.left - menuRect.width;
						}
						let y = clickPosition.top;
						if (y + menuRect.height > docSize.height + docSize.scrollTop) {
							y = docSize.height - menuRect.height;
						}

						x = x - parentNodeRect.left;
						y = y - parentNodeRect.top;

						return contextMenu.show({x: x, y: y}, rowId);
					}.bind(this)).then(function() {
						contextMenu.dom.style.visibility = '';
						contextMenu.dom.focus();
					}.bind(this));
				}
			}.bind(this), 'row');
		},
		set visibleXClass(xClassesId) {
			this.grid.settings.indexRows = xClassesId;
			this.grid.render();
			let show = false;
			if (this.grid.settings.indexRows.length === 0) {
				show = true;
			}
			xClassSearchWrapper.showNotFound(show);
		},
		get visibleXClass() {
			return this.grid.settings.indexRow;
		},
		initGridData: function(xClasses) {
			const head = new Map();
			const rows = new Map();
			head.set('col1', {
				label: 'Column1',
				width: '100%',
				resize: true
			});

			rows.set(AnyXClass.id, AnyXClass);
			xClasses.forEach(function(xClass, id) {
				rows.set(id, xClass);
			});

			xClassSearchControl.grid.head = head;
			xClassSearchControl.grid.rows = rows;
			this.grid.rows.get = function(key, prop) {
				const value = this._store.get(key);
				if (value) {
					if (prop) {
						return value[prop];
					}
					return value;
				}
			};
		},
		parseXClasses: function(xClassTrees) {
			const xClasses = new Map();
			const setXClassesRecursive = function(refId, refObj, edges, level) {
				const childrenRefs = edges[refId];
				const xClass = refObj[refId];
				xClass.level = level;
				xClasses.set(xClass.id, xClass);
				if (childrenRefs && childrenRefs.length > 0) {
					childrenRefs.forEach(function(childRef) {
						setXClassesRecursive(childRef, refObj, edges, level + 1);
						xClass.addChildXClass(refObj[childRef], xClassSearchControl.logicState);
					});
				}
			};
			xClassTrees.forEach(function(xClassTree) {
				const hierarchy = JSON.parse(aras.getItemProperty(xClassTree, 'classification_hierarchy'));
				const xClassesItems = ArasModules.xml.selectNodes(xClassTree, './/Item[@type="xClass"]');
				const xClassTreeId = xClassTree.getAttribute('id') || '';
				const refObjItem = {};
				const edges = {};
				xClassesItems.forEach(function(xClassItem) {
					const name = aras.getItemProperty(xClassItem, 'label') || aras.getItemProperty(xClassItem, 'name');
					const ref_id = aras.getItemProperty(xClassItem, 'ref_id');
					const id = aras.getItemProperty(xClassItem, 'id');
					refObjItem[ref_id] = new XClass(id, name, xClassTreeId);
				});
				hierarchy.forEach(function(edge) {
					const from = edge.fromRefId || 'roots';
					const to = edge.toRefId;
					if (!edges[from]) {
						edges[from] = [];
					}
					edges[from].push(to);
				});
				edges.roots.forEach(function(root) {
					setXClassesRecursive(root, refObjItem, edges, 1);
				});
			});
			return xClasses;
		},
		search: function(text) {
			const searchXClasses = [];
			this.allXClasses.forEach(function(xClass, id) {
				if (xClass.find(text)) {
					searchXClasses.push(id);
				}
			});
			this.visibleXClass = searchXClasses;
			this.isFilteredMode = true;
		},
		clearFoundXClasses: function() {
			this.grid.settings.indexRows.forEach(function(rowId) {
				const xClass = this.grid.rows.get(rowId);
				xClass.clearSearchData();
			}.bind(this));
		},
		clearFilters: function() {
			this.allXClasses.forEach(function(xClass) {
				xClass.isFiltered = false;
			});
			this.grid.render();
		},
		getQueryAml: function() {
			if ((!this.xClasses || this.xClasses.size === 0) && (!this.relationshipXClasses || this.relationshipXClasses.size === 0)) {
				return this.currentSearchQuery.xml;
			}

			let amlQuery = AnyXClass.getAml(itemTypeName, relationshipItemTypeName, this.currentSearchQuery) || '';
			if (amlQuery) {
				return amlQuery;
			}

			const queryXml = aras.createXMLDocument();
			let nodeToInsert = queryXml.appendChild(queryXml.createElement(this.logicState.tagName));
			let relatedItemNode = null;
			let includeRelshipXClassSearchCriteria = false;
			let includeXClassSearchCriteria = false;
			if (relationshipItemTypeName) {
				this.relationshipXClasses.forEach(function(xClass) {
					if (xClass.checkbox.state.getAml(nodeToInsert, xClass.id, relationshipItemTypeName, this.logicState) && !includeRelshipXClassSearchCriteria) {
						includeRelshipXClassSearchCriteria = true;
					}
				}, this);
				relatedItemNode = queryXml.createElement('related_id');
				nodeToInsert = relatedItemNode.appendChild(queryXml.createElement('Item'));
				nodeToInsert.setAttribute('type', itemTypeName);
				nodeToInsert.setAttribute('action', 'get');
				nodeToInsert = nodeToInsert.appendChild(queryXml.createElement(this.logicState.tagName));
			}
			this.xClasses.forEach(function(xClass) {
				if (xClass.checkbox.state.getAml(nodeToInsert, xClass.id, itemTypeName, this.logicState) && !includeXClassSearchCriteria) {
					includeXClassSearchCriteria = true;
				}
			}, this);

			if (relationshipItemTypeName && includeXClassSearchCriteria) {
				queryXml.documentElement.appendChild(relatedItemNode);
			}

			if (includeRelshipXClassSearchCriteria || includeXClassSearchCriteria) {
				queryXml.documentElement.setAttribute('xClassSearchCriteria', '1');
				this.currentSearchQuery.appendChild(queryXml.documentElement);
			}

			return this.currentSearchQuery.xml;
		},
		parseQuery: function(query) {
			this.currentSearchQuery = query;
			if ((!this.xClasses || this.xClasses.size === 0) && (!this.relationshipXClasses || this.relationshipXClasses.size === 0)) {
				return;
			}

			const isQueryAnyXClass = AnyXClass.parseItemAml(query, itemTypeName, relationshipItemTypeName);
			if (!isQueryAnyXClass) {
				const xClassSearchCriteria = query.selectSingleNode('//node()[@xClassSearchCriteria="1"]');
				if (xClassSearchCriteria) {
					if (xClassSearchCriteria.tagName.toUpperCase() === XClassSearchCheckbox.LogicStates.AND.tagName.toUpperCase()) {
						this.logicState = XClassSearchCheckbox.LogicStates.AND;
					} else if (xClassSearchCriteria.tagName.toUpperCase() === XClassSearchCheckbox.LogicStates.OR.tagName.toUpperCase()) {
						this.logicState = XClassSearchCheckbox.LogicStates.OR;
					}
					const setStateByXClassIds = function(ids, xClasses, state, prefix) {
						ids.forEach(function(id) {
							if (prefix) {
								id = prefix + id;
							}
							const xClass = xClasses.get(id);
							if (xClass) {
								xClass.setCheckboxState(state);
							}
						});
					};
					Object.keys(XClassSearchCheckbox.States).forEach(function(checkboxStateKey) {
						const checkboxState = XClassSearchCheckbox.States[checkboxStateKey];
						const ids = checkboxState.getXClassesIdByMarkerState.call(checkboxState, xClassSearchCriteria, this.logicState, itemTypeName, relationshipItemTypeName);
						const relationshipsIds = checkboxState.getXClassesIdByMarkerState.call(checkboxState, xClassSearchCriteria, this.logicState, relationshipItemTypeName,
							relationshipItemTypeName);
						setStateByXClassIds(ids, this.xClasses, checkboxState);
						setStateByXClassIds(relationshipsIds, this.relationshipXClasses, checkboxState, relationshipIdPrefix);
					}, this);
				}
			}

			if (this.supportXClassSearch) {
				this.clearXClassSearchCriteria(this.currentSearchQuery);
			}
		},
		getQueryForXClassBar: function() {
			const searchTips = [];
			const logicStateLabel = aras.getResource(pathToResource, 'xClassSearchControl.xclassbar.checkbox.logic.' + this.logicState.tagName);
			if (AnyXClass.checkbox.state === XClassSearchCheckbox.States.STATE_HARD_CHECKED) {
				const label = aras.getResource(pathToResource, 'xClassSearchControl.xclassbar.checkbox.all_checked');
				searchTips.push('<mark>' + label + '</mark>');
			} else if (AnyXClass.checkbox.state === XClassSearchCheckbox.States.STATE_HARD_UNCHECKED) {
				const label = aras.getResource(pathToResource, 'xClassSearchControl.xclassbar.checkbox.all_unchecked');
				searchTips.push('<mark>' + label + '</mark>');
			} else {
				this.allXClasses.forEach(function(xClass) {
					switch (xClass.checkbox.state) {
						case XClassSearchCheckbox.States.STATE_CHECKED:
						case XClassSearchCheckbox.States.STATE_UNCHECKED:
						case XClassSearchCheckbox.States.STATE_HARD_CHECKED:
						case XClassSearchCheckbox.States.STATE_HARD_UNCHECKED:
							if (searchTips.length > 0) {
								searchTips.push(logicStateLabel);
							}
							const checkboxStateLabel = aras.getResource(pathToResource,
								'xClassSearchControl.xclassbar.checkbox.' + xClass.checkbox.state.class,
								'<mark>' + xClass.name + '</mark>');
							searchTips.push(checkboxStateLabel);
							break;
					}
				});
			}
			return searchTips.join(' ');
		},
		clearXClassSearchCriteria: function(queryNode) {
			const xClassSearchCriteria = queryNode.selectSingleNode('//node()[@xClassSearchCriteria="1"]');
			if (xClassSearchCriteria) {
				queryNode.removeChild(xClassSearchCriteria);
			}
		},
		updateOrderCheckboxes: function() {
			this.allXClasses.forEach(function(xClass) {
				xClass.checkbox.generateOrderStates(xClass.children.length > 0, this.logicState === XClassSearchCheckbox.LogicStates.AND);
			}.bind(this));
			this.grid.render();
		},
		AnyXClass: AnyXClass
	};

	window.xClassSearchControl = xClassSearchControl;
})();

/** ..\Modules\aras.innovator.ExtendedClassification\scripts\xClassSearch\xClassSearchFilters.js **/
(function() {
	const pathToResource = '../Modules/aras.innovator.ExtendedClassification/';

	const xClassSearchFilters = {
		ALL: {
			value: 'ALL',
			get label() {
				if (!this._label) {
					this._label = aras.getResource(pathToResource, 'xClassSearchControl.filter.all');
				}
				return this._label;
			},
			filter: function() {
				const filteredXClasses = [];
				xClassSearchControl.allXClasses.forEach(function(xClass, id) {
					filteredXClasses.push(id);
				});
				if (xClassSearchControl.xClasses && xClassSearchControl.xClasses.size > 0 ||
					xClassSearchControl.relationshipXClasses && xClassSearchControl.relationshipXClasses.size > 0) {
					filteredXClasses.unshift('any_classification');
				}
				return filteredXClasses;
			}
		},
		ACTIVE_FILTERS: {
			value: 'ACTIVE_FILTERS',
			get label() {
				if (!this._label) {
					this._label = aras.getResource(pathToResource, 'xClassSearchControl.filter.active_filters');
				}
				return this._label;
			},
			get filterPanelLabel() {
				if (!this._filterPanelLabel) {
					this._filterPanelLabel = aras.getResource(pathToResource, 'xClassSearchControl.filter.panel.active_filters');
				}
				return this._filterPanelLabel;
			},
			filter: function() {
				const filteredXClasses = [];
				xClassSearchControl.allXClasses.forEach(function(xClass, id) {
					if (xClass.isFiltered) {
						filteredXClasses.push(id);
					}
				});
				return filteredXClasses;
			}
		},
		ACTIVE_SEARCHES: {
			value: 'ACTIVE_SEARCHES',
			get label() {
				if (!this._label) {
					this._label = aras.getResource(pathToResource, 'xClassSearchControl.filter.active_searches');
				}
				return this._label;
			},
			get filterPanelLabel() {
				if (!this._filterPanelLabel) {
					this._filterPanelLabel = aras.getResource(pathToResource, 'xClassSearchControl.filter.panel.active_searches');
				}
				return this._filterPanelLabel;
			},
			filter: function() {
				const filteredXClasses = [];
				xClassSearchControl.allXClasses.forEach(function(xClass, id) {
					if (xClass.checkbox.state !== XClassSearchCheckbox.States.STATE_DEFAULT) {
						filteredXClasses.push(id);
					}
				});
				return filteredXClasses;
			}
		},
		ALL_ACTIVE: {
			value: 'ALL_ACTIVE',
			get label() {
				if (!this._label) {
					this._label = aras.getResource(pathToResource, 'xClassSearchControl.filter.all_active');
				}
				return this._label;
			},
			get filterPanelLabel() {
				if (!this._filterPanelLabel) {
					this._filterPanelLabel = aras.getResource(pathToResource, 'xClassSearchControl.filter.panel.all_active');
				}
				return this._filterPanelLabel;
			},
			filter: function() {
				const filteredXClasses = [];
				xClassSearchControl.allXClasses.forEach(function(xClass, id) {
					if (xClass.isFiltered === true || xClass.checkbox.state !== XClassSearchCheckbox.States.STATE_DEFAULT) {
						filteredXClasses.push(id);
					}
				});
				return filteredXClasses;
			}
		}
	};
	xClassSearchFilters.getFilterByValue = function(value) {
		const filter = Object.keys(this).find(function(filter) {
			return this[filter].value === value;
		}, this);
		return this[filter];
	};
	Object.defineProperty(xClassSearchFilters, 'getFilterByValue', {enumerable: false});

	window.xClassSearchFilters = xClassSearchFilters;
})();

/** ..\Modules\aras.innovator.ExtendedClassification\scripts\xClassSearch\xClassSearchWrapper.js **/
(function() {
	const pathToResource = '../Modules/aras.innovator.ExtendedClassification/';

	const xClassSearchWrapper = {
		xClassSearchControl: xClassSearchControl,
		initResources: function() {
			this.recources = {
				headerLabel: aras.getResource(pathToResource, 'xClassSearchControl'),
				showAll: aras.getResource(pathToResource, 'classEditor.tree.show_all'),
				classFiltered: aras.getResource(pathToResource, 'classEditor.tree.class_filtered'),
				notFound: aras.getResource(pathToResource, 'xClassSearchControl.not_found')
			};
		},
		initData: function(currentItemTypeName, xClassTrees, query, supportXClassSearch, relationshipTypeName, relationshipXClassTrees) {
			itemTypeName = currentItemTypeName;
			relationshipItemTypeName = relationshipTypeName;
			xClassSearchControl.supportXClassSearch = supportXClassSearch || false;
			xClassSearchControl.init(xClassTrees, relationshipXClassTrees);
			if (query) {
				xClassSearchControl.parseQuery(query);
			}

			if (!xClassSearchControl.currentSearchFilter) {
				xClassSearchControl.currentSearchFilter = xClassSearchFilters.ALL;
			}
			this.setFilter(xClassSearchControl.currentSearchFilter.value);

			if (!xClassSearchControl.logicState) {
				xClassSearchControl.logicState = XClassSearchCheckbox.LogicStates.AND;
			}
			this.setLogicStateHtml(xClassSearchControl.logicState);
		},
		attachTo: function(node) {
			this.node = node;
			const sideHeader = document.createElement('div');
			sideHeader.classList.add('side-header');
			sideHeader.innerHTML = '<span>' + this.recources.headerLabel + '</span>';
			this.node.appendChild(sideHeader);
			this.node.appendChild(this._getHtmlSearchPanel());
			this.node.appendChild(this._getHtmlFilteredPanel());
			this.node.appendChild(this._getHtmlNotFoundBlock());
			this.node.appendChild(this._getHtmlTreeBlock());
			xClassSearchControl.initGrid(this.treeBlock);
		},
		setFilter: function(filterValue) {
			const state = xClassSearchFilters.getFilterByValue(filterValue);
			xClassSearchControl.setSearchFilter(state);
			if (state === xClassSearchFilters.ALL) {
				this.setVisibleFilteredPanel(false);
			} else {
				this.setVisibleFilteredPanel(true);
				this.setFilteredPanelText(state.filterPanelLabel);
			}
			this.setSelectFilter(state.value);
			this.searchInput.querySelector('input[name="search"]').value = '';
		},
		setSelectFilter: function(value) {
			const select = this.node.querySelector('.search-filter');
			const prevSelectItem = select.querySelector('.selected');
			const nextSelectedItem = select.querySelector('li[data-value="' + value + '"]');
			if (prevSelectItem) {
				prevSelectItem.classList.remove('selected');
			}
			if (nextSelectedItem) {
				nextSelectedItem.classList.add('selected');
			}
		},
		setVisibleFilteredPanel: function(show) {
			this.filteredPanel.classList.toggle('hidden', !show);
		},
		setFilteredPanelText: function(text) {
			this.filteredPanel.firstChild.textContent = text;
		},
		updateColumnSelection: function() {
			if (columnSelectionControl.grid && columnSelectionControl.grid.rows._store.size > 0) {
				const xClassesIds = xClassSearchFilters.ACTIVE_FILTERS.filter();
				const xClassesArr = [];
				const allXClasses = xClassSearchControl.allXClasses;
				xClassesIds.forEach(function(id) {
					const xClass = allXClasses.get(id);
					if (xClass) {
						xClassesArr.push(xClass);
					}
				});
				columnSelectionControl.filterByXClasses(xClassesArr);
			}
		},
		toggle: function() {
			if (!this.node) {
				return;
			}
			this.node.classList.toggle('hidden');
			xClassSearchControl.grid.render();
		},
		search: function(event) {
			const searchValue = event.target.value;
			if (!searchValue) {
				xClassSearchWrapper.setFilter('ALL');
				return;
			}
			xClassSearchControl.search(searchValue);
			this.setVisibleFilteredPanel(true);
			const label = aras.getResource(pathToResource, 'xClassSearchControl.filter.panel.search_by', searchValue);
			this.setFilteredPanelText(label);
		},
		clearFilters: function() {
			xClassSearchControl.clearFilters();
		},
		showNotFound: function(show) {
			if (!this.node) {
				return;
			}
			this.notFoundBlock.classList.toggle('hidden', !show);
			this.treeBlock.classList.toggle('hidden', show);
		},
		setLogicStateHtml: function(logicState) {
			this.logicFilterBtn.className = '';
			this.logicFilterBtn.classList.add('logic-filter', logicState.class);
			xClassSearchControl.updateOrderCheckboxes();
		},
		onClickLogic: function() {
			xClassSearchControl.logicState = xClassSearchControl.logicState === XClassSearchCheckbox.LogicStates.AND ?
				XClassSearchCheckbox.LogicStates.OR :
				XClassSearchCheckbox.LogicStates.AND;
			this.setLogicStateHtml(xClassSearchControl.logicState);
		},
		toggleXClassBar: function() {
			this.xClassBarBtn.classList.toggle('aras-compat-toolbar__toggle-button');
			columnSelectionMediator.xClassBarWrapper.toggle();
			columnSelectionMediator.updateXClassBar();
			columnSelectionMediator.xClassBarWrapper.setQueryText(xClassSearchControl.getQueryForXClassBar());
		},
		setClickableFilters: function(canClickable) {
			if (xClassSearchControl.canClickableFilters !== canClickable) {
				xClassSearchControl.canClickableFilters = canClickable;
				this.clearFilters();
			}
		},
		_getHtmlSearchPanel: function() {
			this.searchPanel = document.createElement('div');
			this.searchPanel.classList.add('search-panel');

			this.xClassBarBtn = document.createElement('span');
			this.xClassBarBtn.classList.add('xClassBar-toggle-btn');
			this.xClassBarBtn.addEventListener('click', xClassSearchWrapper.toggleXClassBar.bind(this));
			if (columnSelectionMediator && columnSelectionMediator.xClassBarWrapper &&
				!columnSelectionMediator.xClassBarWrapper.container.classList.contains('hidden')) {
				this.xClassBarBtn.classList.toggle('aras-compat-toolbar__toggle-button');
			}

			this.searchInput = document.createElement('div');
			this.searchInput.classList.add('search');
			let selectHtml = '<div class="dropdown-filter">' +
				'<div class="dropdown-btn"><span></span></div>' +
				'<ul class="search-filter aras-hide" tabindex="0">';
			for (let key in xClassSearchFilters) {
				const filter = xClassSearchFilters[key];
				selectHtml += '<li data-value="' + filter.value + '">' + filter.label + '</li>';
			}
			selectHtml += '</ul></div>';
			this.searchInput.innerHTML = '<input name="search" oninput="xClassSearchWrapper.search(event)">' +
				'<span class="loupe-icon"></span>' + selectHtml;

			const dropdown = this.searchInput.querySelector('.dropdown-filter');
			const dropdownButton = this.searchInput.querySelector('.dropdown-btn');
			const searchFilter = this.searchInput.querySelector('.search-filter');
			searchFilter.addEventListener('blur', function() {
				searchFilter.classList.toggle('aras-hide', true);
			});
			dropdownButton.addEventListener('mousedown', function() {
				searchFilter.classList.toggle('aras-hide');
				if (!searchFilter.classList.contains('aras-hide')) {
					setTimeout(function() {
						searchFilter.focus();
					}, 0);
				}
			});
			searchFilter.addEventListener('click', (function(e) {
				const value = e.target.dataset.value;
				if (value) {
					this.setFilter(value);
					columnSelectionControl.node.parentElement.focus();
					searchFilter.classList.toggle('aras-hide', true);
				}
			}).bind(this));

			this.logicFilterBtn = document.createElement('span');
			this.logicFilterBtn.classList.add('logic-filter');
			this.logicFilterBtn.addEventListener('click', xClassSearchWrapper.onClickLogic.bind(this));

			this.searchPanel.appendChild(this.xClassBarBtn);
			this.searchPanel.appendChild(this.searchInput);
			this.searchPanel.appendChild(this.logicFilterBtn);

			return this.searchPanel;
		},
		_getHtmlFilteredPanel: function() {
			this.filteredPanel = document.createElement('div');
			this.filteredPanel.classList.add('filtered', 'hidden');
			this.filteredPanel.innerHTML = '<span>' + this.recources.classFiltered + '</span>' +
				'<span onclick="xClassSearchWrapper.setFilter(\'' + xClassSearchFilters.ALL.value + '\')">' + this.recources.showAll + '</span>';
			return this.filteredPanel;
		},
		_getHtmlNotFoundBlock: function() {
			this.notFoundBlock = document.createElement('div');
			this.notFoundBlock.classList.add('no-result', 'hidden');
			this.notFoundBlock.innerText = this.recources.notFound;
			return this.notFoundBlock;
		},
		_getHtmlTreeBlock: function() {
			this.treeBlock = document.createElement('div');
			this.treeBlock.classList.add('tree');
			return this.treeBlock;
		}
	};

	window.xClassSearchWrapper = xClassSearchWrapper;
})();

/** ..\Modules\aras.innovator.ExtendedClassification\scripts\xClassSearch\xClassBar.js **/
function XClassBar(itemTypeName, xClassBarNode, relationshipItemTypeName) {
	this.itemTypeName = itemTypeName;
	this.container = xClassBarNode;
	if (relationshipItemTypeName) {
		this.relationshipItemTypeName = relationshipItemTypeName;
	}
}

XClassBar.prototype.toggle = function() {
	if (!this.container) {
		return;
	}
	this.container.classList.toggle('hidden');
};

XClassBar.prototype.updateXClassBar = function(itemId, relationshipItemId) {
	const showBar = this.container && !this.container.classList.contains('hidden');
	if (!showBar || (this.previousSelect.itemId === itemId &&
		this.previousSelect.relationshipItemId === relationshipItemId)) {
		return;
	}

	const relationshipIdPrefix = 'R_';
	const relationshipNamePrefix = '[R]';

	let xClasses = [];
	let aml = '<AML>' +
					'<Item type="xClassifiableItem_xClass" action="get" select="itemtype,related_id(name, label)">' +
						'<OR>';
	let needToDoRequest = false;

	const dataArr = [
		{
			xTrees: columnSelectionControl.xClassTrees,
			itemId: itemId,
			itemTypeName: this.itemTypeName,
			isRelationship: false
		},
		{
			xTrees: columnSelectionControl.relationshipsXClassTrees,
			itemId: relationshipItemId,
			itemTypeName: this.relationshipItemTypeName,
			isRelationship: true
		}
	];

	let relItemTypeXClassName;
	dataArr.forEach(function(data) {
		if (data.xTrees && data.xTrees.length > 0 && data.itemId && data.itemTypeName) {
			if (data.isRelationship) {
				relItemTypeXClassName = data.itemTypeName + '_xClass';
			}
			needToDoRequest = true;
			aml += '<AND>' +
						'<itemtype condition="in" by="id">' +
							'<Item type="ItemType" action="get">' +
								'<name>' + data.itemTypeName + '_xClass</name>' +
							'</Item>' +
						'</itemtype>' +
						'<source_id>' + data.itemId + '</source_id>' +
					'</AND>';
		}
	});

	aml +=			'</OR>' +
				'</Item>' +
			'</AML>';

	if (needToDoRequest) {
		const relItemTypeXClassId = relItemTypeXClassName ? aras.getItemTypeId(relItemTypeXClassName) : null;
		const responseItem = aras.IomInnovator.applyAML(aml);
		const xClassifiableItemXClassNodes = ArasModules.xml.selectNodes(responseItem.dom, aras.XPathResult() + '/Item[@type="xClassifiableItem_xClass"]');
		xClasses = xClassifiableItemXClassNodes.map(function(xClassifiableItemXClass) {
			const isRelationship = relItemTypeXClassId && relItemTypeXClassId === aras.getItemProperty(xClassifiableItemXClass, 'itemtype');
			const xClass = ArasModules.xml.selectSingleNode(xClassifiableItemXClass, 'related_id/Item[@type="xClass"]');
			let name = aras.getItemProperty(xClass, 'label') || aras.getItemProperty(xClass, 'name');
			let id = aras.getItemProperty(xClass, 'id');
			if (isRelationship) {
				name = relationshipNamePrefix + ' ' + name;
				id = relationshipIdPrefix + id;
			}
			return {
				name: name,
				id: id
			};
		});
	}

	this.setVisibleXClasses(xClasses);
	this.previousSelect = {
		itemId: itemId,
		relationshipItemId: relationshipItemId
	};
};

XClassBar.prototype.setVisibleXClasses = function(xClasses) {
	if (!this.container) {
		return;
	}
	this.clear();
	let xml = '<?xml version="1.0" encoding="utf-8"?>' +
					'<toolbarapplet buttonsize="26,25">' +
						'<toolbar id="xclassbar">';
	xClasses.forEach(function(xClass) {
		xml += '<text id="' + xClass.id + '" value="' + xClass.name + '" />';
	});
	xml += '</toolbar>' +
	'</toolbarapplet>';

	this.toolbar.loadToolbarFromStr(xml);
	this.toolbar.show();
};

XClassBar.prototype.clear = function() {
	if (this.toolbar && this.toolbar._toolbar) {
		this.toolbar._toolbar.destroy();
		this.toolbar._toolbar = null;
	}
};

XClassBar.prototype.setQueryText = function(criteriaTextHtml) {
	const criteriaTextNode = this.criteriaPane.querySelector('.criteria-text');
	if (criteriaTextNode.firstChild) {
		criteriaTextNode.removeChild(criteriaTextNode.firstChild);
	}

	const textContainer = document.createElement('span');
	criteriaTextNode.appendChild(textContainer);
	textContainer.innerHTML = criteriaTextHtml;
	if (criteriaTextHtml) {
		criteriaTextNode.setAttribute('title', criteriaTextHtml.replace(/<mark>/g, '').replace(/<\/mark>/g, ''));
	}
	this.criteriaContainer.classList.toggle('xclass-bar__container-hidden', !criteriaTextHtml);
};

Object.defineProperty(XClassBar.prototype, 'container', {
	get: function() {
		return this.htmlBlock;
	},
	set: function(container) {
		this.clear();
		container.innerHTML = '';
		this.previousSelect = {};
		this.htmlBlock = container;

		this.criteriaContainer = document.createElement('div');
		this.criteriaContainer.id = 'xClassCriteriaContainer';
		this.criteriaContainer.classList.add('xclass-bar__container');
		this.criteriaPane = document.createElement('div');
		this.criteriaPane.classList.add('xclass-criteria-panel');
		const criteriaTextNode = document.createElement('div');
		criteriaTextNode.classList.add('criteria-text');
		const clearCriteriaBtn = document.createElement('span');
		clearCriteriaBtn.classList.add('clear-xclass-criteria');
		clearCriteriaBtn.addEventListener('click', function() {
			this.setQueryText();
			columnSelectionMediator.clearSearch();
		}.bind(this));
		this.criteriaPane.appendChild(criteriaTextNode);
		this.criteriaPane.appendChild(clearCriteriaBtn);

		const toolbarBlock = document.createElement('div');
		toolbarBlock.id = 'toolbarXClassBarContainer';
		toolbarBlock.classList.add('xclass-bar__container');
		this.toolbar = new ToolbarWrapper({
			id: 'xClassBarContainer',
			connectId: toolbarBlock.id,
			useCompatToolbar: true
		});
		const infernoFlags = ArasModules.utils.infernoFlags;
		CompatToolbar.formatters.text = function(data) {
			const innerText = Inferno.createVNode(Inferno.getFlagsForElementVnode('span'), 'span', 'xclass-bar-name',
			Inferno.createTextVNode(data.item.value), infernoFlags.hasVNodeChildren);
			return Inferno.createVNode(Inferno.getFlagsForElementVnode('span'), 'span', 'xclass-bar-item', innerText,
			infernoFlags.hasVNodeChildren, {'data-id': data.item.id});
		};

		this.criteriaContainer.appendChild(this.criteriaPane);
		this.htmlBlock.appendChild(this.criteriaContainer);
		this.htmlBlock.appendChild(toolbarBlock);
	}
});

/** ..\Modules\aras.innovator.ExtendedClassification\scripts\columnSelection.js **/
(function() {
	var columnSelectionControl = {
		filter: {
			classes: true,
			properties: true,
			text: ''
		},
		data: {}
	};
	var selectOptions;
	var currItemType;
	let currentRelationshipsItemType;
	const relationshipIdPrefix = 'R_';
	const relationshipNamePrefix = '[R]';
	const xPropertyNameRegExp = new RegExp('^(' + relationshipNamePrefix.replace('[', '\\[').replace(']', '\\]') + ' )?xp-');

	var toggleTreeDisplay = function(bool) {
		var tree = columnSelectionControl.node.querySelector('.tree');
		var noPropsContainer = columnSelectionControl.node.querySelector('.no-properties');

		if (bool) {
			tree.classList.remove('aras-hide');
			noPropsContainer.classList.add('aras-hide');
		} else {
			tree.classList.add('aras-hide');
			noPropsContainer.classList.remove('aras-hide');
		}
	};

	var manageSelectAllBlock = function() {
		var selectAllBlock = columnSelectionControl.node.querySelector('.select-all');

		var mixed = columnSelectionControl.grid.settings.indexRows.length;
		selectAllBlock.classList.toggle('column-select-block__select-all_invisible', mixed === 0);
		columnSelectionControl.grid.settings.indexRows.forEach(function(idx) {
			const row = columnSelectionControl.grid.rows.get(idx);
			if (row && row.hidden) {
				mixed--;
			}
		});
		let value = false;
		let isMixed = false;
		if (mixed === columnSelectionControl.grid.settings.indexRows.length) {
			value = true;
		} else if (mixed > 0) {
			isMixed = true;
			value = true;
		}
		selectAllBlock.firstChild.checked = value;
		if (isMixed) {
			selectAllBlock.classList.add('mixed');
		} else {
			selectAllBlock.classList.remove('mixed');
		}
	};

	columnSelectionControl.initResources = function() {
		columnSelectionControl.resources = {
			columnsLabel: aras.getResource('../Modules/aras.innovator.ExtendedClassification/', 'toolbar_columns_label'),
			showAll: aras.getResource('../Modules/aras.innovator.ExtendedClassification/', 'classEditor.tree.show_all'),
			noPropertiesLabel: aras.getResource('../Modules/aras.innovator.ExtendedClassification/', 'classEditor.tree.no_properties'),
			columnsFilteredLabel: aras.getResource('../Modules/aras.innovator.ExtendedClassification/', 'classEditor.tree.filtered'),
			selectOptionsAllLabel: aras.getResource('../Modules/aras.innovator.ExtendedClassification/', 'classEditor.tree.select.all_and_extended'),
			selectOptionsStandardLabel: aras.getResource('../Modules/aras.innovator.ExtendedClassification/', 'classEditor.tree.select.standard'),
			selectOptionsExtendedLabel: aras.getResource('../Modules/aras.innovator.ExtendedClassification/', 'classEditor.tree.select.all_extended'),
			selectOptionsRelationshipLabel: aras.getResource('../Modules/aras.innovator.ExtendedClassification/', 'classEditor.tree.select.relationship')
		};
	};

	columnSelectionControl.selectProperty = function(selectedType) {
		let indexRows = [];
		let xClassCanFilter = false;
		columnSelectionControl.loadedType = selectedType;
		switch (selectedType) {
			case 'All':
			case 'Extended':
			case 'Relationship':
				indexRows = columnSelectionControl.loadProperties(selectedType);
				xClassCanFilter = true;
				break;
			case 'itemType':
				indexRows = columnSelectionControl.loadProperties(selectedType);
				break;
		}
		columnSelectionControl.setVisibleFilteredPanel(false);
		xClassSearchWrapper.setClickableFilters(xClassCanFilter);
		columnSelectionControl.renderTreeData(indexRows);
		if (indexRows && indexRows.length > 0) {
			toggleTreeDisplay(true);
		} else {
			toggleTreeDisplay(false);
		}
	};

	columnSelectionControl.attachTo = function(node) {
		columnSelectionControl.node = node;
		const controlTemplate =
'<div class="column-select-block-flex">' +
	'<div class="column-selection">' +
		'<div class="side-header">' +
			'<span>' + columnSelectionControl.resources.columnsLabel + '</span>' +
		'</div>' +
		'<div class="properties-selector-block aras-form">' +
			'<div class="properties-selector-block-upper">' +
				'<div>' +
					'<label class="aras-form-boolean select-all">' +
						'<input type="checkbox" />' +
						'<span><span/>' +
					'</label>' +
					'<div class="property-types"></div>' +
				'</div>' +
			'</div>' +
		'</div>' +
		'<div class="filtered hidden">' +
			'<span>' + columnSelectionControl.resources.columnsFilteredLabel + '</span>' +
			'<span onclick="columnSelectionControl.showAll()">' + columnSelectionControl.resources.showAll + '</span>' +
		'</div>' +
		'<div class="tree aras-hide"></div>' +
		'<div class="no-properties">' + columnSelectionControl.resources.noPropertiesLabel + '</div>' +
	'</div>' +
	'<div class="xclass-search-block hidden"></div>' +
'</div>';
		node.innerHTML = controlTemplate;
		columnSelectionControl.grid = new Grid(node.querySelector('.tree'), {multiSelect: false});

		node.querySelector('.property-types').addEventListener('change', function(e) {
			const option = columnSelectionControl.typeAhead.state.value;

			if (!option) {
				columnSelectionControl.renderTreeData([]);
				toggleTreeDisplay(false);
				return;
			}
			columnSelectionControl.selectProperty(option);
		});

		xClassSearchWrapper.attachTo(node.querySelector('.xclass-search-block'));
		columnSelectionControl.grid.getCellType = function() {
			return 'richCheckbox';
		};

		Grid.formatters.richCheckbox = function(headId, rowId, value, grid) {
			var hidden = grid.rows.get(rowId, 'hidden');
			var mixed = grid.rows.get(rowId, 'mixed');
			var checkbox = {
				className: 'aras-grid-row-cell_boolean',
				children: [{
					tag: 'label',
					className: 'aras-form-boolean' + (mixed ? ' mixed' : ''),
					children: [
						{
							tag: 'input',
							attrs: {
								type: 'checkbox',
								checked: !hidden
							}
						},
						{
							tag: 'span'
						}
					]
				}, {
					tag: 'div',
					className: 'checkbox-title',
					children: [value]
				}]
			};

			return checkbox;
		};

		const selectAllCheckbox = node.querySelector('.select-all');
		selectAllCheckbox.addEventListener('change', function(event) {
			const checkbox = this.firstChild;
			if (this.classList.contains('mixed')) {
				this.classList.remove('mixed');
				checkbox.checked = true;
			}
			const value = checkbox.checked;
			columnSelectionControl.grid.settings.indexRows.forEach(function(id) {
				columnSelectionControl.grid.rows.set(id, !value, 'hidden');
			});
			columnSelectionControl.grid.render();
			columnSelectionControl.isDirty = true;
		});

		columnSelectionControl.grid.on('click', function(rowId, event) {
			if (event.target.closest('.aras-form-boolean') && event.target.tagName !== 'INPUT') {
				columnSelectionControl.toggleRowSelection(rowId);
				columnSelectionControl.isDirty = true;
			}
		}, 'row');
	};

	columnSelectionControl.toggleRowSelection = function(rowId) {
		var column = columnSelectionControl.grid.rows.get(rowId);
		var sourceColumn = columnSelectionControl.columns.find(function(col) {
			return col.propertyId === rowId;
		});

		if (!sourceColumn) {
			sourceColumn = columnSelectionControl.relationshipsColumns.find(function(col) {
				return col.propertyId === rowId;
			});
		}

		if (column && column.children) {
			if (column.mixed && !column.hidden) {
				column.hidden = false;
				column.children.forEach(function(childId) {
					var child = columnSelectionControl.grid.rows.get(childId);
					child.hidden = false;
					columnSelectionControl.grid.rows.set(childId, child);
				});
			} else if (!column.mixed && !column.hidden) {
				column.hidden = true;
				column.children.forEach(function(childId) {
					var child = columnSelectionControl.grid.rows.get(childId);
					child.hidden = true;
					columnSelectionControl.grid.rows.set(childId, child);
				});
			} else {
				column.hidden = false;
				column.children.forEach(function(childId) {
					var child = columnSelectionControl.grid.rows.get(childId);
					child.hidden = false;
					columnSelectionControl.grid.rows.set(childId, child);
				});
			}
			column.mixed = false;
			columnSelectionControl.grid.rows.set(rowId, column);
		} else {
			if (column) {
				column.hidden = !column.hidden;
				sourceColumn.hidden = column.hidden;
				columnSelectionControl.grid.rows.set(rowId, column);
			} else {
				sourceColumn.hidden = true;
			}
			manageSelectAllBlock();
		}
	};

	function getITProps(columns) {
		return columns.filter(function(column) {
			if (column.name && xPropertyNameRegExp.test(column.name)) {
				return false;
			}
			return true;
		});
	}

	function getITxProps(columns) {
		return columns.filter(function(column) {
			if (columnSelectionControl.itemTypeExplicitXPropsIds.indexOf(column.propertyId) > -1) {
				return true;
			}
		});
	}

	function getRelITxProps(columns) {
		return columns.filter(function(column) {
			if (columnSelectionControl.relationshipsTypeExplicitXPropsIds.indexOf(column.propertyId.slice(2)) > -1) {
				return true;
			}
		});
	}

	function getTreeXClassProps(xClassTrees, columns, idPrefix) {
		idPrefix = idPrefix || '';
		const props = [];
		const propertyIdToColumn = {};

		columns.forEach(function(column) {
			propertyIdToColumn[column.propertyId] = column;
		});

		const fillPropsArr = function(xProps) {
			Array.prototype.forEach.call(xProps, function(xProp) {
				const xPropId = aras.getItemProperty(xProp, 'id');
				const column = propertyIdToColumn[idPrefix + xPropId];
				if (column) {
					props.push(column);
				}
			});
		};

		if (aras.getItemProperty(currItemType, 'implementation_type') !== 'polymorphic') {
			if (xClassTrees) {
				Array.prototype.forEach.call(xClassTrees, function(xClassTree) {
					if (xClassTree) {
						const xClasses = xClassTree.selectNodes('Relationships/Item');
						Array.prototype.forEach.call(xClasses, function(xClass) {
							const xProps = xClass.selectNodes('Relationships/Item[not(inactive="1")]/related_id/Item');
							fillPropsArr(xProps);
						});
					}
				});
			}
		} else {
			const polyXProps = currItemType.selectNodes('Relationships/Item[@type="xItemTypeAllowedProperty"]/related_id/Item');
			fillPropsArr(polyXProps);
		}
		return props;
	}

	function sortByLabel(a, b) {
		if (a.label.toLowerCase() > b.label.toLowerCase()) {
			return 1;
		} else if (a.label.toLowerCase() < b.label.toLowerCase()) {
			return -1;
		}
		return 0;
	}

	columnSelectionControl.loadProperties = function(type, xClass) {
		function sortByOrder(a, b) {
			if (a.propSortOrder > b.propSortOrder) {
				return 1;
			} else if (a.propSortOrder < b.propSortOrder) {
				return -1;
			} else {
				return 0;
			}
		}

		const indexRows = [];
		const addPropsToRows = function(column, idx) {
			indexRows.push(column.propertyId);
		};

		let itProps;
		let itXProps;
		let xClassProps;
		let allExtendedProps;

		const addPropsRelationship = function() {
			if (columnSelectionControl.relationshipsColumns && columnSelectionControl.relationshipsColumns.length > 0) {
				itProps = getITProps(columnSelectionControl.relationshipsColumns);
				itProps.sort(sortByOrder);
				itProps.forEach(addPropsToRows);
				itXProps = getRelITxProps(columnSelectionControl.relationshipsColumns);
				xClassProps = getTreeXClassProps(columnSelectionControl.relationshipsXClassTrees, columnSelectionControl.relationshipsColumns, relationshipIdPrefix);
				allExtendedProps = itXProps.concat(xClassProps);
				allExtendedProps.sort(sortByLabel);
				allExtendedProps.forEach(addPropsToRows);
			}
		};

		if (type === 'itemType') {
			itProps = getITProps(columnSelectionControl.columns);
			itProps.sort(sortByOrder);
			itProps.forEach(addPropsToRows);
			itXProps = getITxProps(columnSelectionControl.columns);
			itXProps.forEach(addPropsToRows);
		} else if (type === 'All') {
			itProps = getITProps(columnSelectionControl.columns);
			itProps.sort(sortByOrder);
			itProps.forEach(addPropsToRows);
			itXProps = getITxProps(columnSelectionControl.columns);
			xClassProps = getTreeXClassProps(columnSelectionControl.xClassTrees, columnSelectionControl.columns);
			allExtendedProps = itXProps.concat(xClassProps);
			allExtendedProps.sort(sortByLabel);
			allExtendedProps.forEach(addPropsToRows);
			addPropsRelationship();
		} else if (type === 'Extended') {
			xClassProps = getTreeXClassProps(columnSelectionControl.xClassTrees, columnSelectionControl.columns);
			xClassProps.sort(sortByLabel);
			xClassProps.forEach(addPropsToRows);
		} else if (type === 'Relationship') {
			addPropsRelationship();
		} else {
			const treesToFilter = xClass.isRelationship ? columnSelectionControl.relationshipsXClassTrees : columnSelectionControl.xClassTrees;
			const xClassTree = Array.prototype.find.call(treesToFilter, function(xClassTree) {
				return xClass.xClassTreeId === aras.getItemProperty(xClassTree, 'id');
			});
			let props = Array.prototype.slice.call(getInheritedProperties(type, xClassTree));
			props.forEach(function(xProp) {
				const propDefinition = xProp.selectSingleNode('related_id/Item');
				const id = xClass.isRelationship ? relationshipIdPrefix + aras.getItemProperty(propDefinition, 'id') : aras.getItemProperty(propDefinition, 'id');
				indexRows.push(id);
			});
		}
		return indexRows;
	};

	function getInheritedProperties(id, xClassTree) {
		var selectedClass = xClassTree.selectSingleNode('Relationships/Item[@id="' + id + '"]');
		var selectedRefId = aras.getItemProperty(selectedClass, 'ref_id');
		var childToParentIds = {};
		var hieararchy = JSON.parse(aras.getItemProperty(xClassTree, 'classification_hierarchy'));
		hieararchy.forEach(function(edge) {
			childToParentIds[edge.toRefId] = edge.fromRefId;
		});
		var parentChainIds = [id];
		var getParentId = function(childId) {
			var parentId = childToParentIds[childId];
			if (parentId) {
				var xClass = xClassTree.selectSingleNode('Relationships/Item[ref_id="' + parentId + '"]');
				parentChainIds.push(xClass.getAttribute('id'));
				getParentId(parentId);
			}
		};
		getParentId(selectedRefId);
		if (parentChainIds.length > 0) {
			var clientXPropertyDefinitions = xClassTree.selectNodes('Relationships/Item[@id=\'' +
				parentChainIds.join('\' or @id=\'') + '\']/Relationships/Item[not(inactive=\'1\')]');
			return clientXPropertyDefinitions;
		}
	}

	function fillSelectEl(select) {
		if (select.getElementsByTagName('aras-filter-list').length > 0) {
			return;
		}

		selectOptions = [{
			label: columnSelectionControl.resources.selectOptionsAllLabel,
			value: 'All',
			static: true
		}, {
			label: columnSelectionControl.resources.selectOptionsStandardLabel,
			value: 'itemType',
			static: true
		}, {
			label: columnSelectionControl.resources.selectOptionsExtendedLabel,
			value: 'Extended',
			static: true
		}];

		if (searchLocation === 'Relationships Grid') {
			selectOptions.splice(2, 0, {
					label: columnSelectionControl.resources.selectOptionsRelationshipLabel,
					value: 'Relationship',
					static: true
				}
			);
		}

		const typeAhead = document.createElement('aras-filter-list');
		typeAhead.setState({
			list: selectOptions,
			searchableBranch: true
		});
		columnSelectionControl.typeAhead = typeAhead;
		typeAhead.format = function(template) {
			var button = template.children[2];
			button.className += ' dropdown-arrow';
			button.events = Object.assign(button.events || {}, {onClick: function() {
				typeAhead.setState({
					shown: true,
					focus: true,
					showAll: true,
					searchableBranch: true
				});
			}});
			return template;
		};
		select.appendChild(typeAhead);
	}

	columnSelectionControl.initTree = function(itemTypeName, columns, xClassTrees, relationshipsTypeName, relationshipsColumns, relationshipsXClassTrees) {
		columnSelectionControl.columns = columns;
		columnSelectionControl.xClassTrees = xClassTrees;
		columnSelectionControl.relationshipsColumns = relationshipsColumns;
		columnSelectionControl.relationshipsXClassTrees = relationshipsXClassTrees;
		fillSelectEl(columnSelectionControl.node.querySelector('.property-types'));

		if (itemTypeName) {
			currItemType = aras.getItemTypeForClient(itemTypeName).node;
			const explicitXProps = currItemType.selectNodes('Relationships/Item[@type="ItemType_xPropertyDefinition"]/related_id/Item');
			columnSelectionControl.itemTypeExplicitXPropsIds = Array.prototype.map.call(explicitXProps, function(xProp) {
				return aras.getItemProperty(xProp, 'id');
			});
		}

		if (relationshipsTypeName) {
			currentRelationshipsItemType = aras.getItemTypeForClient(relationshipsTypeName).node;
			const explicitXProps = currentRelationshipsItemType.selectNodes('Relationships/Item[@type="ItemType_xPropertyDefinition"]/related_id/Item');
			columnSelectionControl.relationshipsTypeExplicitXPropsIds = Array.prototype.map.call(explicitXProps, function(xProp) {
				return aras.getItemProperty(xProp, 'id');
			});
		}

		columnSelectionControl.initGridWithAllColumns();
		columnSelectionControl.isDirty = false;
	};

	columnSelectionControl.initGridWithAllColumns = function() {
		const head = new Map();
		const rows = new Map();
		head.set('col1', {
			label: 'Column1',
			width: '100%',
			resize: true
		});
		const addPropsToRows = function(column, idx) {
			rows.set(column.propertyId, {
				col1: column.label,
				name: column.name,
				colIndex: column.colNumber,
				hidden: column.hidden,
				propertyId: column.propertyId
			});
		};
		let props = getITProps(columnSelectionControl.columns);
		props.forEach(addPropsToRows);

		props = getITxProps(columnSelectionControl.columns);
		props.forEach(addPropsToRows);

		props = getTreeXClassProps(columnSelectionControl.xClassTrees, columnSelectionControl.columns);
		props.forEach(addPropsToRows);
		if (columnSelectionControl.relationshipsColumns &&
			columnSelectionControl.relationshipsColumns.length > 0 &&
			columnSelectionControl.xClassTrees) {
			props = getITProps(columnSelectionControl.relationshipsColumns);
			props.forEach(addPropsToRows);

			props = getRelITxProps(columnSelectionControl.relationshipsColumns);
			props.forEach(addPropsToRows);

			props = getTreeXClassProps(columnSelectionControl.relationshipsXClassTrees, columnSelectionControl.relationshipsColumns, relationshipIdPrefix);
			props.forEach(addPropsToRows);
		}

		columnSelectionControl.grid.head = head;
		columnSelectionControl.grid.rows = rows;
	};

	columnSelectionControl.renderTreeData = function(indexRows) {
		const uniqueSet = new Set(indexRows);
		const rows = [];
		uniqueSet.forEach(function(row) {
			rows.push(row);
		});
		columnSelectionControl.grid.settings.indexRows = rows;
		columnSelectionControl.grid.render();
		manageSelectAllBlock();
	};

	columnSelectionControl.filterByXClasses = function(xClasses) {
		const xClassProperties = [];
		xClasses.forEach(function(xClass) {
			const indexRows = columnSelectionControl.loadProperties(xClass.id, xClass);
			xClassProperties.push(indexRows);
		});

		const unsortedProperties = Array.prototype.concat.apply([], xClassProperties);
		const propEntries = unsortedProperties.map(function(propertyId) {
			const entry = columnSelectionControl.grid.rows._store.get(propertyId);
			const label = entry.col1 || entry.name;
			return {label: label, id: entry.propertyId};
		});

		const sortedProperties = propEntries
			.sort(sortByLabel)
			.map(function(entry) {
				return entry.id;
			});

		columnSelectionControl.renderTreeData(sortedProperties);

		if (xClasses.length === 0) {
			columnSelectionControl.showAll();
		} else {
			columnSelectionControl.setVisibleFilteredPanel(true);
			let showTree = true;
			if (sortedProperties.length === 0) {
				showTree = false;
			}
			toggleTreeDisplay(showTree);
		}
	};

	columnSelectionControl.showAll = function() {
		columnSelectionControl.setVisibleFilteredPanel(false);
		xClassSearchWrapper.clearFilters();
		columnSelectionControl.selectProperty(columnSelectionControl.typeAhead.state.list[0].value);
		columnSelectionControl.typeAhead.setState({
			value: columnSelectionControl.typeAhead.state.list[0].value
		});
	};

	columnSelectionControl.setVisibleFilteredPanel = function(visible) {
		if (!columnSelectionControl.node) {
			return;
		}
		const filterNode = columnSelectionControl.node.querySelector('.filtered');
		filterNode.classList.toggle('hidden', !visible);
	};

	window.columnSelectionControl = columnSelectionControl;

	columnSelectionControl.getCheckedColumns = function() {
		const columns = [];
		columnSelectionControl.grid.rows._store.forEach(function(column) {
			columns.push(column);
		});
		return columns.filter(function(column) {
			return !column.children;
		});
	};
})();

/** ..\Modules\aras.innovator.ExtendedClassification\scripts\BaseColumnSelectionMediator.js **/
function BaseColumnSelectionMediator(xClassBarNode) {
	this.xClassBarWrapper = new XClassBar(itemTypeName, xClassBarNode);
}

BaseColumnSelectionMediator.prototype.cuiToolbarFormatter = function(data) {
	const infernoFlags = ArasModules.utils.infernoFlags;
	const createColumnSelectionControl = function(data) {
		const columnSelectNode = Inferno.createVNode(
			Inferno.getFlagsForElementVnode('div'),
			'div',
			'column-select-block hidden',
			null,
			infernoFlags.hasInvalidChildren,
			{
				id: 'column_select_block'
			}
		);
		const columnSelectDropdownBox = Inferno.createVNode(
			Inferno.getFlagsForElementVnode('div'),
			'div',
			'aras-dropdown',
			columnSelectNode,
			infernoFlags.hasVNodeChildren
		);
		const contentNodes = [];
		if (data.item.image) {
			const iconNode = ArasModules.SvgManager.createInfernoVNode(data.item.image);

			iconNode.className = 'aras-button__icon';
			contentNodes.push(iconNode);
		}
		contentNodes.push(
			Inferno.createVNode(
				Inferno.getFlagsForElementVnode('span'),
				'span',
				'aras-button__menu-arrow',
				null,
				infernoFlags.hasInvalidChildren
			)
		);
		const buttonNodeAttributes = {
			title: data.item.tooltip_template,
			disabled: data.item.disabled,
			'dropdown-button': ''
		};
		const buttonNode = Inferno.createVNode(
			Inferno.getFlagsForElementVnode('button'),
			'button',
			'aras-button',
			contentNodes,
			infernoFlags.unknownChildren,
			buttonNodeAttributes
		);
		const columnSelectContainer = Inferno.createVNode(
			Inferno.getFlagsForElementVnode('aras-dropdown'),
			'aras-dropdown',
			'column-select-dropdown aras-dropdown-container',
			[buttonNode, columnSelectDropdownBox],
			infernoFlags.hasNonKeyedChildren
		);
		return columnSelectContainer;
	};
	return Inferno.createComponentVNode(
		infernoFlags.componentFunction,
		createColumnSelectionControl,
		data,
		null,
		{
			onComponentDidMount: this._onComponentDidMount.bind(this)
		}
	);
};

BaseColumnSelectionMediator.prototype._onComponentDidMount = function(columnSelectContainer) {
	columnSelectionControl.attachTo(document.getElementById('column_select_block'));
	columnSelectContainer.addEventListener('dropdownbeforeopen', this.columnSelectionOnBeforeOpen.bind(this));
	columnSelectContainer.addEventListener('dropdownclosed', this.apply.bind(this));
};

BaseColumnSelectionMediator.prototype.columnSelectionOnBeforeOpen = function() {
	const data = this.getDataForColumnSelection(itemTypeName, visiblePropNds);
	columnSelectionControl.node.classList.remove('hidden');
	columnSelectionControl.initTree(itemTypeName, data.columns, data.xClassList);
	const currentSearchQueryItem = aras.newIOMItem();
	currentSearchQueryItem.loadAML(searchContainer._getSearchQueryAML());
	xClassSearchWrapper.initData(itemTypeName,
		data.xClassList,
		currentSearchQueryItem.node,
		currentSearchMode.supportXClassSearch);
	xClassSearchWrapper.updateColumnSelection();
	xClassSearchWrapper.toggle();
};

BaseColumnSelectionMediator.prototype.clearSearch = function() {
	this.xClassBarWrapper.setQueryText();
	xClassSearchWrapper.xClassSearchControl.clearXClassSearchCriteria(currQryItem.item);
	searchContainer._updateAutoSavedSearch(currQryItem.item.xml);
	searchContainer._setAml(currQryItem.item.xml);
};

BaseColumnSelectionMediator.prototype.closeColumnSelectionWindow = function() {
	if (window.columnSelectionControl && columnSelectionControl.node) {
		columnSelectionControl.node.classList.add('hidden');
	}
};

BaseColumnSelectionMediator.prototype.closeXClassBarWindow = function() {
	if (this.xClassBarWrapper && this.xClassBarWrapper.container) {
		this.xClassBarWrapper.container.classList.add('hidden');
	}
};

BaseColumnSelectionMediator.prototype.updateXClassBar = function() {
	this.xClassBarWrapper.updateXClassBar(grid.getSelectedId());
};

BaseColumnSelectionMediator.prototype.getDataForColumnSelection = function(itemTypeName, propsNds) {
	const xClassList = xPropertiesUtils.getXClassificationTreesForItemType(aras.getItemTypeId(itemTypeName));
	return {
		columns: this.getColumns(propsNds),
		xClassList: xClassList
	};
};

BaseColumnSelectionMediator.prototype.apply = function() {
	if (currentSearchMode.supportXClassSearch) {
		let amlQuery = xClassSearchWrapper.xClassSearchControl.getQueryAml();
		if (amlQuery) {
			const xClassSearch = aras.newIOMItem();
			xClassSearch.loadAML(amlQuery);
			searchContainer._updateAutoSavedSearch(xClassSearch.node.xml);
			searchContainer._setAml(xClassSearch.node.xml);
		}
		if (!this.xClassBarWrapper.container.classList.contains('hidden')) {
			let xClassTextQuery = xClassSearchWrapper.xClassSearchControl.getQueryForXClassBar();
			this.xClassBarWrapper.setQueryText(xClassTextQuery);
		}
	}
	if (columnSelectionControl.isDirty) {
		const columns = columnSelectionControl.getCheckedColumns();
		const columnIdToColumn = {};
		columnSelectionControl.columns.forEach(function(column) {
			columnIdToColumn[column.propertyId] = column;
		});
		columns.forEach(function(column) {
			grid.SetColumnVisible(columnIdToColumn[column.propertyId].colNumber, !column.hidden, columnIdToColumn[column.propertyId].width);
		}.bind(this));
		const key = aras.MetadataCache.CreateCacheKey('getSelectCriteria', itemTypeID, searchContainer.searchLocation == 'Relationships Grid');
		aras.MetadataCache.SetItem(key);

		const newSearch = aras.newIOMItem();
		newSearch.loadAML(searchContainer._getDefaultSearchQueryAML());

		const oldSearch = aras.newIOMItem();
		oldSearch.loadAML(searchContainer._getSearchQueryAML());
		oldSearch.setAttribute('select', newSearch.getAttribute('select'));

		searchContainer._updateAutoSavedSearch(oldSearch.node.xml);
		searchContainer._setAml(oldSearch.node.xml);
		searchContainer.runSearch();
	}
};

BaseColumnSelectionMediator.prototype.getColumns = function(propNds) {
	const colOrderArr = grid.getLogicalColumnOrder().split(';');
	const propertyItems = {};
	let propsToShow = [];

	if (propNds) {
		for (let i = 0; i < propNds.length; i++) {
			const propertyName = aras.getItemProperty(propNds[i], 'name');
			propertyItems[propertyName] = propNds[i];
		}
	}

	for (let i = 0; i < colOrderArr.length; i++) {
		let isValidProperty = false;
		let hidden = grid.getColWidth(i) == 0 ? true : false;
		let propertyLabel = '';
		let propertyWidth = 100;
		let columnName = grid.GetColumnName(i);
		let propertyName;
		let propertyId;
		let propSortOrder;

		if (columnName === 'L') {
			propertyLabel = aras.getResource('', 'common.claimed');
			propertyWidth = 32;
			isValidProperty = true;
		} else {
			propertyName = columnName.substr(0, columnName.length - 2);
			const propertyItem = propertyItems[propertyName];
			if (propertyItem) {
				const tempWidth = parseInt(aras.getItemProperty(propertyItem, 'column_width'));
				propSortOrder = parseInt(aras.getItemProperty(propertyItem, 'sort_order'));

				propertyLabel = aras.getItemProperty(propertyItem, 'label') || propertyName;
				propertyId = aras.getItemProperty(propertyItem, 'id');

				if (!isNaN(tempWidth)) {
					propertyWidth = tempWidth;
				}
				isValidProperty = true;
			}
		}
		if (!isValidProperty) {
			continue;
		}
		propsToShow.push({
			colNumber: i,
			propSortOrder: propSortOrder || 0,
			name: propertyName,
			label: propertyLabel,
			width: propertyWidth,
			hidden: hidden,
			propertyId: propertyId
		});
	}
	return propsToShow;
};

/** ..\Modules\aras.innovator.ExtendedClassification\scripts\RelationshipColumnSelectionMediator.js **/
function RelationshipColumnSelectionMediator(xClassBarNode) {
	BaseColumnSelectionMediator.apply(this, arguments);
	this.xClassBarWrapper = new XClassBar(relatedItemTypeName, xClassBarNode, relationshipTypeName);
}
RelationshipColumnSelectionMediator.prototype = Object.create(BaseColumnSelectionMediator.prototype);
RelationshipColumnSelectionMediator.prototype.constructor = RelationshipColumnSelectionMediator;

RelationshipColumnSelectionMediator.prototype._onComponentDidMount = function(columnSelectContainer) {
	columnSelectionControl.attachTo(columnSelectContainer.querySelector('#column_select_block'));
	columnSelectContainer.addEventListener('dropdownbeforeopen', this.columnSelectionOnBeforeOpen.bind(this));
	columnSelectContainer.addEventListener('dropdownclosed', this.apply.bind(this));

	xClassSearchWrapper.xClassBarBtn.addEventListener('click', function(e) {
		refreshGridSize();
	});
};

RelationshipColumnSelectionMediator.prototype.columnSelectionOnBeforeOpen = function() {
	const dataRelatedItem = this.getDataForColumnSelection(relatedItemTypeName, RelatedVisibleProps);
	const dataRelationshipItem = this.getDataForColumnSelection(relationshipTypeName, DescByVisibleProps, true);
	columnSelectionControl.initTree(relatedItemTypeName,
		dataRelatedItem.columns, dataRelatedItem.xClassList,
		relationshipTypeName, dataRelationshipItem.columns, dataRelationshipItem.xClassList);
	const currentSearchQueryItem = aras.newIOMItem();
	currentSearchQueryItem.loadAML(searchContainer._getSearchQueryAML());
	xClassSearchWrapper.initData(relatedItemTypeName,
		dataRelatedItem.xClassList,
		currentSearchQueryItem.node,
		currentSearchMode.supportXClassSearch,
		relationshipTypeName,
		dataRelationshipItem.xClassList);
	columnSelectionControl.typeAhead.setState({
		value: columnSelectionControl.typeAhead.state.list[0].label
	});
	columnSelectionControl.selectProperty(columnSelectionControl.typeAhead.state.list[0].value);
	xClassSearchWrapper.updateColumnSelection();
	xClassSearchWrapper.toggle();
};

RelationshipColumnSelectionMediator.prototype.updateXClassBar = function() {
	const relID = grid.getSelectedId();
	const relItem = item.selectSingleNode('Relationships/Item[@id="' + relID + '"]');
	this.xClassBarWrapper.updateXClassBar(aras.getItemProperty(relItem, 'related_id'), relID);
};

RelationshipColumnSelectionMediator.prototype.apply = function() {
	if (currentSearchMode.supportXClassSearch) {
		let amlQuery = xClassSearchWrapper.xClassSearchControl.getQueryAml();
		if (amlQuery) {
			const xClassSearch = aras.newIOMItem();
			xClassSearch.loadAML(amlQuery);
			searchContainer._updateAutoSavedSearch(xClassSearch.node.xml);
			searchContainer._setAml(xClassSearch.node.xml);
		}
		if (!this.xClassBarWrapper.container.classList.contains('hidden')) {
			let xClassTextQuery = xClassSearchWrapper.xClassSearchControl.getQueryForXClassBar();
			this.xClassBarWrapper.setQueryText(xClassTextQuery);
			refreshGridSize();
		}
	}
	if (columnSelectionControl.isDirty) {
		const columns = columnSelectionControl.getCheckedColumns();
		const columnIdToColumn = {};
		columnSelectionControl.columns.forEach(function(column) {
			columnIdToColumn[column.propertyId] = column;
		});
		columnSelectionControl.relationshipsColumns.forEach(function(column) {
			columnIdToColumn[column.propertyId] = column;
		});
		columns.forEach(function(column) {
			grid.SetColumnVisible(columnIdToColumn[column.propertyId].colNumber, !column.hidden, columnIdToColumn[column.propertyId].width);
		}.bind(this));
		const key = aras.MetadataCache.CreateCacheKey('getSelectCriteria', itemTypeID, searchContainer.searchLocation == 'Relationships Grid');
		aras.MetadataCache.SetItem(key);

		const newSearch = aras.newIOMItem();
		newSearch.loadAML(searchContainer._getDefaultSearchQueryAML());

		const oldSearch = aras.newIOMItem();
		oldSearch.loadAML(searchContainer._getSearchQueryAML());
		oldSearch.setAttribute('select', newSearch.getAttribute('select'));

		searchContainer._updateAutoSavedSearch(oldSearch.node.xml);
		searchContainer._setAml(oldSearch.node.xml);
		searchContainer.runSearch();
	}
};

RelationshipColumnSelectionMediator.prototype.getColumns = function(propNds, isRelationship) {
	const colOrderArr = grid.getLogicalColumnOrder().split(';');
	const DRL = isRelationship ? 'D' : 'R';
	let propsToShow = [];
	const relationshipIdPrefix = 'R_';
	const relationshipNamePrefix = '[R]';

	const propertyItems = Array.prototype.reduce.call(propNds || [], function(res, node) {
		const name = aras.getItemProperty(node, 'name');
		res[name] = node;
		return res;
	}, {});

	return colOrderArr.filter(function(columnName) {
		return (columnName === 'L' && !isRelationship) ||
				(columnName.endsWith(DRL) && propertyItems[columnName.slice(0, -2)]);
	}).map(function(columnName) {
		const index = grid.getColumnIndex(columnName);
		const hidden = grid.getColWidth(index) === 0;
		if (columnName === 'L' && !isRelationship) {
			return {
				colNumber: index,
				propSortOrder: 0,
				label: aras.getResource('', 'common.claimed'),
				width: 24,
				hidden: hidden,
				DRL: DRL
			};
		}

		let propertyName = columnName.slice(0, -2);
		const propertyItem = propertyItems[propertyName];
		const propertyWidth = parseInt(aras.getItemProperty(propertyItem, 'column_width') || 100);
		const propSortOrder = parseInt(aras.getItemProperty(propertyItem, 'sort_order') || 0);
		let propertyLabel = aras.getItemProperty(propertyItem, 'label', propertyName);
		let propertyId = aras.getItemProperty(propertyItem, 'id');

		if (isRelationship) {
			propertyId = relationshipIdPrefix + propertyId;
			propertyName = relationshipNamePrefix + ' ' + propertyName;
			propertyLabel = relationshipNamePrefix + ' ' + propertyLabel;
		}
		return {
			colNumber: index,
			propSortOrder: propSortOrder,
			name: propertyName,
			label: propertyLabel,
			width: propertyWidth,
			hidden: hidden,
			propertyId: propertyId,
			DRL: DRL
		};
	});
};

RelationshipColumnSelectionMediator.prototype.getDataForColumnSelection = function(itemTypeName, propsNds, isRelationship) {
	const xClassList = xPropertiesUtils.getXClassificationTreesForItemType(aras.getItemTypeId(itemTypeName));
	return {
		columns: this.getColumns(propsNds, isRelationship),
		xClassList: xClassList
	};
};

/** ..\Modules\aras.innovator.ExtendedClassification\scripts\ColumnSelectionMediatorFactory.js **/
const ColumnSelectionMediatorFactory = {
	CreateBaseMediator: function ColumnSelectionMediatorFactoryCreateBaseMediator(xClassBarNode) {
		return new BaseColumnSelectionMediator(xClassBarNode);
	},
	CreateRelationshipMediator: function ColumnSelectionMediatorFactoryCreateRelationshipMediator(xClassBarNode) {
		return new RelationshipColumnSelectionMediator(xClassBarNode);
	}
};

/** StaticVariablesStorage.js **/
//This file contains definition of class StaticVariablesStorage.
//IMPORTANT: this file initializes global variable __staticVariablesStorage.

function StaticVariablesStorage() {
}

StaticVariablesStorage.prototype.setNewObject = function StaticVariablesStorageSetNewObject(keyName) {
	var res = {};
	this[keyName] = res;
	return res;
};

////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
if (window.__staticVariablesStorage === true) {
	//this is treated as a flag that it's required to make current window a place where static variables storage is kept
	window.__staticVariablesStorage = new StaticVariablesStorage();
} else {
	//otherwise we have to find main window and take a reference to __staticVariablesStorage from there.
	var down = 1;
	var up = 2;
	var queue = [{
		window: window,
		direction: up
	}];

	var processUp = function(window) {
		var nextWindow;
		var direction;
		if (window.opener) {
			nextWindow = window.opener;
		} else if (window.dialogArguments && window.dialogArguments.opener) {
			nextWindow = window.dialogArguments.opener;
		} else if (window !== window.parent) {
			nextWindow = window.parent;
			direction = up;
		} else {
			return;
		}
		queue.push({
			window: nextWindow,
			direction: direction
		});
	};

	var processDown = function(window) {
		var frames = window.frames;
		for (var i = 0; i < frames.length; i++) {
			var frame = frames[i];
			if (frame !== window) {
				queue.push({
					window: frame,
					direction: down
				});
			}
		}
	};

	var node;
	while (queue.length > 0) {
		node = queue.shift();
		try {
			if (node.window.__staticVariablesStorage) {
				break;
			}
		} catch (e) {
			console.log('Access to __staticVariablesStorage denied.');
			// maybe permission denied to access property
		}
		switch (node.direction) {
			case up:
				processUp(node.window);
				break;
			case down:
				processDown(node.window);
				break;
			default:
				processUp(node.window);
				processDown(node.window);
				break;
		}
	}

	// expect that node.window contain __staticVariablesStorage
	if (node.window.closed) {
		throw new Error(1, 'Main window is closed.');
	}

	if (!node.window.__staticVariablesStorage) {
		throw new Error(2, 'Main window doesn\'t contain __staticVariablesStorage.');
	}
	window.__staticVariablesStorage = node.window.__staticVariablesStorage;
}

/** ModulesHelper.js **/
var ModulesManager = {
	_mapPathClasses: function(classes) {
		return classes.map(function(classIndex) {
			const tmp = classIndex.split('/');
			const moduleName = tmp.slice(0, tmp.length - 1).join('/'); // get everything before last segment.
			const className = tmp.slice(-1)[0]; // class name is last segment
			return aras.getBaseURL(
				'/Modules/' + moduleName + '/Scripts/Classes/' + className + '.js'
			);
		});
	},
	// class format -> ['moduleName/className', 'moduleName2/className2']
	using: function(classes, func) {
		const mapClass = this._mapPathClasses(classes);

		return new Promise(function(resolve) {
			require(mapClass, function() {
				if (func instanceof Function) {
					resolve(func.apply(null, arguments));
				} else {
					resolve(arguments[0]);
				}
			});
		});
	},
	define: function(classes, classFullName, func, isAsync) {
		const mapClass = this._mapPathClasses(classes);
		define(mapClass, func);
	}
};

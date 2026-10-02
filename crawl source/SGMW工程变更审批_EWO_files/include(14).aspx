
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

/** enumerations.js **/
var Enums = {};

Enums.UrlType = {'None': 0, 'SecurityToken': 1};
Enums.SortType = {'Ascending': 0, 'Descending': 1};
Enums.CheckinManagerFlags = {'None': 0, 'UnlockAfterCheckin': 1};
Enums.CheckoutManagerFlags = {'None': 0, 'UseTransactions': 1};

/** ..\Modules\aras.innovator.core.Core\Scripts\Classes\TopWindowHelper.js **/
var TopWindowHelper;
(function(TopWindowHelper) {
	// Duplicated in dialog.js, PopupMenu.js
	TopWindowHelper.getMostTopWindowWithAras = function(windowObj) {
		var win = windowObj ? windowObj : window;
		var prevWin = win;
		var winWithAras;
		while (win !== win.parent) {
			try {
				// Try access to any property with permission denied.
				var t = win.parent.name;
			} catch (excep) {
				break;
			}
			prevWin = win;
			win = win.parent;
			winWithAras = typeof win.aras !== 'undefined' ? win : winWithAras;
		}
		return winWithAras ? winWithAras : prevWin; // for work Innovator working in iframe case
	};
})(TopWindowHelper || (TopWindowHelper = {}));

/** iom.js **/
function IOMCache(parentArasObj) {
	this.arasObj = parentArasObj;
}

IOMCache.prototype.apply = function IOMCacheApply(itemNd, async) {
	var $Promise = async ? Promise : ArasModules.SyncPromise;

	if (!itemNd) {
		return $Promise.resolve(null);
	}
	var itemID = itemNd.getAttribute('id');
	var itemTypeName = itemNd.getAttribute('type');
	var itemAction = itemNd.getAttribute('action');
	if (itemAction === null) {
		itemAction = '';
	}

	var win = this.arasObj.uiFindWindowEx2(itemNd);

	//special checks for the item of ItemType type
	// <name> tag in itemNd required for next call
	var res;
	if (itemTypeName == 'ItemType') {
		res = this.arasObj.checkItemType(itemNd, win);
	} else {
		res = true;
	}

	if (!res) {
		return $Promise.resolve(null);
	}

	if (itemTypeName) {
		if (itemAction == 'delete') {
			this.arasObj.deleteItem(itemTypeName, itemID, true);
			return $Promise.resolve(null);
		} else if (itemAction == 'purge') {
			this.arasObj.purgeItem(itemTypeName, itemID, true);
			return $Promise.resolve(null);
		}
	}

	//general checks for the item to be saved: all required parameters should be set
	if (itemTypeName) {
		res = this.arasObj.checkItem(itemNd, win);
	} else {
		res = true;
	}

	if (!res) {
		return $Promise.resolve(null);
	}

	res = null;

	var backupCopy = itemNd;
	var oldParent = backupCopy.parentNode;
	itemNd = itemNd.cloneNode(true);
	this.arasObj.prepareItem4Save(itemNd);

	var isTemp = this.arasObj.isTempEx(itemNd);

	if (itemNd.getAttribute('action') == 'add') {
		if (itemTypeName == 'RelationshipType') {
			if (!itemNd.selectSingleNode('relationship_id/Item')) {
				var rsItemNode = itemNd.selectSingleNode('relationship_id');
				if (rsItemNode) {
					var rs = this.arasObj.getItemById('', rsItemNode.text, 0);
					if (rs) {
						rsItemNode.text = '';
						rsItemNode.appendChild(rs.cloneNode(true));
					}
				}
			}
			var tmp001 = itemNd.selectSingleNode('relationship_id/Item');
			if (tmp001 && this.arasObj.getItemProperty(tmp001, 'name') === '') {
				this.arasObj.setItemProperty(tmp001, 'name', this.arasObj.getItemProperty(itemNd, 'name'));
			}
		}
	}

	var files = itemNd.selectNodes('descendant-or-self::Item[@type="File" and (@action="add" or @action="update")]');

	var promise;
	if (files.length === 0) {
		promise = (async ? ArasModules.soap(itemNd.xml, {method: 'ApplyItem', async: true}) : $Promise.resolve(this.arasObj.soapSend('ApplyItem', itemNd.xml)))
			.then(function(res) {
				if (async) {
					res = new SOAPResults(this.arasObj, res.ownerDocument.xml);
				}

				if (res.getFaultCode() !== 0) {
					return null;
				}

				return res.results.selectSingleNode(this.arasObj.XPathResult('/Item'));
			}.bind(this));
	} else {
		var statusMsg = 'Sending of File to Vault...';
		if (async) {
			promise = this.arasObj.sendFilesWithVaultAppletAsync(itemNd, statusMsg);
		} else {
			promise = $Promise.resolve(this.arasObj.sendFilesWithVaultApplet(itemNd, statusMsg));
		}
	}

	return promise.then(function(res) {
		if (!res) {
			return null;
		}

		res.setAttribute('levels', '0');

		var newID = res.getAttribute('id');
		this.arasObj.updateInCacheEx(backupCopy, res);

		if (itemTypeName == 'RelationshipType') {
			var relationshipId = this.arasObj.getItemProperty(itemNd, 'relationship_id');
			if (relationshipId) {
				this.arasObj.removeFromCache(relationshipId);
			}
			this.arasObj.commonProperties.formsCacheById = this.arasObj.newObject();

		} else if (itemTypeName == 'ItemType') {
			var itemName = this.arasObj.getItemProperty(itemNd, 'name');
			this.arasObj.deletePropertyFromObject(this.arasObj.sGridsSetups, itemName);
			this.arasObj.commonProperties.formsCacheById = this.arasObj.newObject();
		}

		if (oldParent) {
			res = oldParent.selectSingleNode('Item[@id="' + newID + '"]');
		} else {
			res = this.arasObj.getFromCache(newID);
		}

		if (!res) {
			return null;
		}

		if (newID != itemID) {
			var itms = this.arasObj.getAffectedItems(itemNd.getAttribute('type'), newID);

			if (itms) {
				for (var i = 0; i < itms.length; i++) {
					var itm = itms[i];
					var itmID = itm.getAttribute('id');
					var affectedItm = this.arasObj.getItemById('', itmID, 0);
					if (affectedItm) {
						if (affectedItm.getAttribute('levels') === null) {
							affectedItm.setAttribute('levels', 1);
						}
						var tmpRes = this.arasObj.loadItems(itm.getAttribute('type'), 'id="' + itmID + '"', affectedItm.getAttribute('levels'));
						if (!tmpRes) {
							continue;
						}
						if (this.arasObj.uiFindWindowEx[itmID]) {
							setTimeout('TopWindowHelper.getMostTopWindowWithAras(window).aras.uiReShowItem(\'' + itmID + '\',\'' + itmID + '\');', 100);
						}
					}
				}
			}
		}

		return res;
	}.bind(this));
};

function Innovator() {
	return TopWindowHelper.getMostTopWindowWithAras(window).aras.newIOMInnovator();
}

function Item(itemTypeName, action, mode) {
	return TopWindowHelper.getMostTopWindowWithAras(window).aras.IomInnovator.newItem(itemTypeName, action);
}

function AuthenticationBrokerClient() { }

AuthenticationBrokerClient.prototype.GetFileDownloadToken = function AuthenticationBrokerClientGetFileDownloadToken(fileId) {
	var innovatorUrl = TopWindowHelper.getMostTopWindowWithAras(window).aras.getServerBaseURL();
	var result = GetSynchronousJSONResponse(innovatorUrl + 'AuthenticationBroker.asmx/GetFileDownloadToken', '{"param":{"fileId":"' + fileId + '"}}');
	var evalMethod = window.eval;
	result = evalMethod('(' + result + ')');
	return result.d;
};

AuthenticationBrokerClient.prototype.GetFilesDownloadTokens = function AuthenticationBrokerClientGetFilesDownloadTokens(fileIds) {
	var body = '{"parameters":[';
	for (var i = 0; i < fileIds.count; i++) {
		body += '{"__type":"FileDownloadParameters","fileId":"' + fileIds(i) + '"},';
	}

	body = body.slice(0, body.length - 1) + ']}';

	var innovatorUrl = TopWindowHelper.getMostTopWindowWithAras(window).aras.getServerBaseURL();
	var result = GetSynchronousJSONResponse(innovatorUrl + 'AuthenticationBroker.asmx/GetFilesDownloadTokens', body);
	var evalMethod = window.eval;
	result = evalMethod('(' + result + ')');
	result = result.d;
	var list = TopWindowHelper.getMostTopWindowWithAras(window).aras.IomFactory.CreateArrayList();
	for (var j = 0, count = result.length - 1; j < count; j++) {
		list.Add(result[j]);
	}
	return list;
};

function LicenseManagerWebServiceClient() {
	this.aras = TopWindowHelper.getMostTopWindowWithAras(window).aras;
	this.actionNamespace = this.aras.arasService.actionNamespace;
	this.iServiceName = this.aras.arasService.serviceName;
	this.licenseServiceUrl = this.aras.getServerBaseURL() + 'Licensing.asmx/';
}

LicenseManagerWebServiceClient.prototype.ConsumeLicense = function(featureName) {
	// don't used soap because request body isn't XML
	var xhr = new XMLHttpRequest();
	var methodName = 'ConsumeLicense';
	var url = this.licenseServiceUrl + methodName;
	xhr.open('POST', url, false);

	var additionalHeaders = this.aras.getHttpHeadersForSoapMessage(methodName);
	Object.keys(additionalHeaders).forEach(function(header) {
		xhr.setRequestHeader(header, additionalHeaders[header]);
	});
	xhr.setRequestHeader('Content-type', 'application/x-www-form-urlencoded; charset=utf-8');

	xhr.send('featureName=' + encodeURIComponent(featureName));

	if (xhr.status !== 200) {
		throw new Error(xhr.responseText);
	}

	var doc = this.aras.createXMLDocument();
	doc.loadXML(xhr.responseText);
	return doc.documentElement.text;
};

function GetSynchronousJSONResponse(url, postData) {
	var xmlhttp = new XMLHttpRequest();

	url = url + '?rnd=' + Math.random(); // to be ensure non-cached version

	xmlhttp.open('POST', url, false);
	xmlhttp.setRequestHeader('Content-Type', 'application/json; charset=utf-8');
	var headers = TopWindowHelper.getMostTopWindowWithAras(window).aras.getHttpHeadersForSoapMessage('GetFileDownloadToken');
	for (var hName in headers) {
		xmlhttp.setRequestHeader(hName, headers[hName]);
	}

	xmlhttp.send(postData);
	return xmlhttp.responseText;
}

/** QueryString.js **/
// (c) Copyright by Aras Corporation, 2004-2007.

/*----------------------------------------
* FileName: QueryString.js
*
* Purpose:
* This file will allow us replace Server-Side working with Query String with
* Client-Side one.
* Functionality emulates ASP Request.QueryString
*
* Currently supported browsers: MS IE 5 and higher
*/

function QueryString(variable) {
	/*----------------------------------------
	* QueryString
	*
	* Purpose:
	* Allows to retrieve the HTTP QUERY_STRING variable by name.
	* Also: location.search emulation is allowed when the currentl html is in frame (see LocationSearches behavior) or in modalDialog.
	* Unparsed QueryString available if you don't specify parameter
	*
	* Arguments:
	* variable - string representing the name of variable you want to retrieve
	*
	*/

	var parsedData = QueryString.parsedData; //stores parsed query string
	//initialized on first request to QueryString

	if (!this.locationSearchEmulated) {
		try {
			//parent.LocationSearches MUST be hash: frame.id -> frame.location.search.
			//Thus the frame url may be without parameters (just specify them in the hash).
			var key = (document.defaultView || document.parentWindow).frameElement.id;
			if (parent.LocationSearches && parent.LocationSearches[key]) {
				this.locationSearchEmulated = parent.LocationSearches[key];
				this.locationSearchEmulated = this.locationSearchEmulated.substr(1);//remove '?'
			}
			if (!this.locationSearchEmulated && window.dialogArguments && window.dialogArguments.LocationSearch) {
				this.locationSearchEmulated = window.dialogArguments.LocationSearch;
			}
		} catch (ex) { }

		//if modal dialog then check: is LocationSearch specified in dialogArguments.
		if (!this.locationSearchEmulated) {
			var das = window.dialogArguments;
			if (das && das.LocationSearch) {
				this.locationSearchEmulated = das.LocationSearch;
			}
		}

		if (!this.locationSearchEmulated) {
			this.locationSearchEmulated = 'empty';
		}
	}

	if (!parsedData) {
		parsedData = {};
		QueryString.parsedData = parsedData;

		var searchStr = (this.locationSearchEmulated != 'empty') ? this.locationSearchEmulated : document.location.search.substr(1);
		var searchArr = searchStr.split('&');
		for (var i = 0; i < searchArr.length; i++) {
			var variableString = searchArr[i];
			var firstEqSignPos = variableString.indexOf('=');
			var variableName;
			var variableValue;

			if (firstEqSignPos == -1) {
				variableName = variableString;
				variableValue = '';
			} else if (firstEqSignPos === 0) {
				continue;
			} else {
				variableName = variableString.substring(0, firstEqSignPos);
				variableValue = unescape(variableString.substr(firstEqSignPos + 1));
			}

			var storedValues = parsedData[variableName];
			if (storedValues === undefined) {
				storedValues = [];
				storedValues.toString = function() {
					return this.join(', ');
				};
				parsedData[variableName] = storedValues;
			}

			storedValues.push(variableValue);
		}
	}

	if (variable === undefined) {
		return document.location.search.substr(1);
	} else {
		var res = parsedData[variable];
		if (res === undefined) {
			res = '';
		}
		return res;
	}
}

QueryString();
 //a call to initialize QueryString

/** soap_object.js **/
// (c) Copyright by Aras Corporation, 2004-2009.
/*----------------------------------------
* FileName: soap_object.js
*
* Purpose:
* Provide a way to comminucate with InnovatorServer using SOAP messages
*
*/

/// <summary>
/// For internal use only.
/// Stores a set of Soap related constants.
/// </summary>
/// <remarks>
/// </remarks>
/// <history>
/// </history>
var SoapConstants = {};

/// <summary>
/// URI to SOAP 1.1 schema
/// </summary>
/// <remarks>
/// </remarks>
/// <history>
/// </history>
SoapConstants.SoapEnvUri = 'http://schemas.xmlsoap.org/soap/envelope/';

/// <summary>
/// Namespace used to return SOAP messages.
/// </summary>
/// <remarks>
/// </remarks>
/// <history>
/// </history>
SoapConstants.SoapNamespace = 'SOAP-ENV';

/// <summary>
/// Opening tags Envelope, Body
/// </summary>
/// <remarks>
/// </remarks>
/// <history>
/// </history>
SoapConstants.EnvelopeBodyStart = '<' + SoapConstants.SoapNamespace + ':Envelope xmlns:' + SoapConstants.SoapNamespace + '="' + SoapConstants.SoapEnvUri + '"><' + SoapConstants.SoapNamespace + ':Body>';

/// <summary>
///
/// </summary>
/// <remarks>
/// </remarks>
/// <history>
/// </history>
SoapConstants.EnvelopeBodyEnd = '</' + SoapConstants.SoapNamespace + ':Body></' + SoapConstants.SoapNamespace + ':Envelope>';

/// <summary>
/// Opening tags Envelope, Body, Fault
/// </summary>
/// <remarks>
/// </remarks>
/// <history>
/// </history>
SoapConstants.EnvelopeBodyFaultStart = SoapConstants.EnvelopeBodyStart + '<' + SoapConstants.SoapNamespace + ':Fault>';

/// <summary>
///
/// </summary>
/// <remarks>
/// </remarks>
/// <history>
/// </history>
SoapConstants.EnvelopeBodyFaultEnd = '</' + SoapConstants.SoapNamespace + ':Fault>' + SoapConstants.EnvelopeBodyEnd;

/// <summary>
/// Check of namespace to be used in XPath
/// </summary>
/// <remarks>
/// </remarks>
/// <history>
/// </history>
SoapConstants.SoapNamespaceCheck = 'namespace-uri()=\'' + SoapConstants.SoapEnvUri + '\' or namespace-uri()=\'\'';

/// <summary>
/// XPath for Envelope
/// </summary>
/// <remarks>
/// </remarks>
/// <history>
/// </history>
SoapConstants.EnvelopeXPath = '*[local-name()=\'Envelope\' and (' + SoapConstants.SoapNamespaceCheck + ')]';

/// <summary>
/// XPath for Body
/// </summary>
/// <remarks>
/// </remarks>
/// <history>
/// </history>
SoapConstants.BodyXPath = '*[local-name()=\'Body\' and (' + SoapConstants.SoapNamespaceCheck + ')]';

/// <summary>
/// XPath for Fault
/// </summary>
/// <remarks>
/// </remarks>
/// <history>
/// </history>
SoapConstants.FaultXPath = '*[local-name()=\'Fault\' and (' + SoapConstants.SoapNamespaceCheck + ')]';

/// <summary>
/// XPath for Envelope/Body
/// </summary>
/// <remarks>
/// </remarks>
/// <history>
/// </history>
SoapConstants.EnvelopeBodyXPath = SoapConstants.EnvelopeXPath + '/' + SoapConstants.BodyXPath;

/// <summary>
/// XPath for Envelope/Body/Fault
/// </summary>
/// <remarks>
/// </remarks>
/// <history>
/// </history>
SoapConstants.EnvelopeBodyFaultXPath = SoapConstants.EnvelopeBodyXPath + '/' + SoapConstants.FaultXPath;

/*
SoapController is designed to manage asynchronous soap requests.
Contains:
callback - function which is called when request is finished
The parameter is passed to constructor.
stop     - readonly parameter. Function which can be used to abort request
*/
function SoapController(callback) {
	this.isInvalid = false;
	this.callback = callback;
	this.stop = null;
}

//marks soap controller instance as invalid. For example when callback is no longer valid (for example when window is closed)
//this will prevent script errors.
SoapController.prototype.markInvalid = function SoapController_markInvalid() {
	this.isInvalid = true;
};

function SOAP(parent) {
	this.parent = parent; //parent aras object
	if (parent.getCurrentLoginName()) {
		ArasModules.soap(null, {
			url: parent.getServerURL(),
			method: 'ApplyItem',
			headers: parent.getHttpHeadersForSoapMessage()
		});
	}
}

SOAP.prototype.send = function SOAP_send(methodName, bodyStr, url, saveChanges, soapController) {
	/*----------------------------------------
	* send
	*
	* Purpose:
	* send xml to InovatorServer and return result.
	* returns SOAPResults object
	*
	* Arguments:
	* methodName - string with Innovator Server method name (ApplyItem, GetItem, ...)
	* bodyStr    - xml string to send
	* url        - url of Innovator Server (by default url is built from this.parent.baseURL)
	*
	* soapController - an instance of SoapController
	*/
	var self = this;
	var arasableObj = this.parent;
	if (!arasableObj || methodName === undefined) {
		return null;
	}
	if (!arasableObj.getCommonPropertyValue('ignoreSessionTimeoutInSoapSend') && arasableObj.getCommonPropertyValue('exitWithoutSavingInProgress')) {
		return new SOAPResults(arasableObj, getFaultXml('The session is closed.'), saveChanges);
	}

	var options = {method: methodName};
	if (url) {
		options.url = url;
	}

	var methodXmlns = '';
	if (methodName.indexOf('/') !== -1) {
		methodXmlns = methodName.substring(0, methodName.lastIndexOf('/'));
		methodName = methodName.substring(methodName.lastIndexOf('/') + 1, methodName.length);
	}
	if (methodXmlns) {
		options.methodNm = methodXmlns;
	}
	var soapStr = removeUnchangedPermission(bodyStr || '');
	if (soapStr && arasableObj.Browser.isIe()) {
		soapStr = soapStr.replace(/\r\n/g, '\n');
	}

	var async = !!(soapController && soapController.callback);
	options.async = async;
	var promise = ArasModules.soap(soapStr, options);
	if (async) {
		soapController.stop = promise.abort;
	}
	var result;
	promise.then(function(resultNode) {
		var text;
		if (resultNode.ownerDocument) {
			var doc = resultNode.ownerDocument;
			text = doc.xml || (new XMLSerializer()).serializeToString(doc);
		} else {
			text = resultNode;
		}
		var finalRetVal = new SOAPResults(arasableObj, text, saveChanges);
		if (methodName && methodName.toLowerCase() === 'validateuser') {
			arasableObj.setCommonPropertyValue('ValidateUserXmlResult', text);
		}
		if (async) {
			if (!soapController.isInvalid) {
				soapController.callback(finalRetVal);
			}
			return;
		}
		result = finalRetVal;
	}).catch(function(xhr) {

		var res = new SOAPResults(arasableObj, xhr.responseText, saveChanges);
		if (async) {
			if (!soapController.isInvalid) {
				soapController.callback(res);
			}
			return;
		}
		result = res;
	});
	return result;

	//function region >>>>>>>>>>>>>>>>>>
	function removeUnchangedPermission(bodyStr) {
		//select all permission_id nodes with attribute origPermission where origPermission
		if (!bodyStr) {
			return bodyStr;
		}
		var workDom = new XmlDocument();
		workDom.loadXML(bodyStr);

		var permissionNodes = workDom.selectNodes('//descendant-or-self::node()[local-name(.) = \'permission_id\' and not(child::Item) and @origPermission]');
		if (permissionNodes && permissionNodes.length > 0) {
			for (var i = 0; i < permissionNodes.length; i++) {
				if (permissionNodes[i].getAttribute('origPermission') == permissionNodes[i].text) {
					var parent = permissionNodes[i].parentNode;
					parent.removeChild(permissionNodes[i]);
				} else {
					permissionNodes[i].removeAttribute('origPermission');
				}
			}
			return workDom.xml;
		}
		return bodyStr;
	}

	function getFaultXml(descr) {
		var faultRetVal = SoapConstants.EnvelopeBodyFaultStart + '<faultcode>' + SoapConstants.SoapNamespace + ':Server</faultcode><detail>' + descr + '</detail>' + SoapConstants.EnvelopeBodyFaultEnd;
		return faultRetVal;
	}
};

SOAP.showExitExcuse = function(arasableObj) {
	var p = {};
	var mainWnd = arasableObj.getMainWindow();
	p.buttons = {};
	p.buttons.btnExit = arasableObj.getResource('', 'soap_object.exit_innovator');
	p.defaultButton = 'btnExit';
	p.btnstyles = {btnExit: ''};
	p.message = arasableObj.getResource('', 'soap_object.session_has_expired');
	p.message += arasableObj.getResource('', 'soap_object.changes_will_be_lost_warning');
	p.aras = arasableObj;
	mainWnd.focus();
	mainWnd.showModalDialog(arasableObj.getScriptsURL() + 'groupChgsDialog.html', p, 'dialogHeight:150px;dialogWidth:300px;center:yes;resizable:no;status:no;help:no;');
};

SOAP.handleSessionTimeout = function(options) {
	options = options || {};

	var aras = TopWindowHelper.getMostTopWindowWithAras(window).aras || window.opener.aras;
	var mainWnd = aras.getMainWindow();
	if (!mainWnd) {
		return Promise.reject();
	}

	var mainAras = mainWnd.aras;
	if (mainAras._handleSessionTimeoutPromise) {
		return mainAras._handleSessionTimeoutPromise;
	}

	var win = TopWindowHelper.getMostTopWindowWithAras(window);
	var argwin = (win.main || win);

	mainWnd.focus();

	var showExitWarning = function() {
		var style = 'style="width: 100px; margin: 5px;"';
		var dialogParams = {
			buttons: {
				btnReturn: aras.getResource('', 'soap_object.login'),
				btnExit: aras.getResource('', 'soap_object.exit_innovator')
			},
			defaultButton: 'btnReturn',
			btnstyles: {btnReturn: style, btnExit: style},
			btnclasses: {btnReturn: '', btnExit: 'cancel_button'},
			message: options.message,
			aras: aras,
			dialogHeight: 150,
			content: 'groupChgsDialog.html',
			dialogWidth: 300,
			dialogHeight: 120,
			center: true,
			ignoreDialogShortcuts: true // Ignore to avoid recursive SessionTimeout on this dialog
		};
		return argwin.ArasModules.Dialog.show('iframe', dialogParams).promise.then(function(tmpRes) {
			if (tmpRes !== 'btnReturn') {
				aras.setCommonPropertyValue('exitWithoutSavingInProgress', true);
				if (mainWnd) {
					mainWnd.onLogoutCommand();
				}
				return Promise.reject();
			}
			return relogin();
		});
	};

	const relogin = function() {
		aras.browserHelper.toggleSpinner(argwin.document, true);
		return aras.OAuthClient.relogin({
				prompt: 'login', // Force to show login form
				login_hint: aras.user.loginName,
				database: aras.user.database
				// TODO: Pass also authentication_type.
				// Currently we based on user preferences handled by OAuthServer
				// which should contain authentication_type.
				// Possible variant of implementation is
				//   authentication_type: aras.user.authenticationType?
				// for which is necessary to return authentication_type from ValidateUser response.
			})
			.then(function() {
				// Run also user.login to avoid possibility of SessionTimeout errors
				// which will case also login dialog.
				return aras.user.login();
			})
			.then(function() {
				aras.browserHelper.toggleSpinner(argwin.document, false);
			})
			.catch(function() {
				aras.browserHelper.toggleSpinner(argwin.document, false);
				return showExitWarning();
			});
	};

	mainAras._handleSessionTimeoutPromise = showExitWarning();

	const resetHandleSessionTimeoutPromise = function() {
		delete mainAras._handleSessionTimeoutPromise;
	};
	mainAras._handleSessionTimeoutPromise
		.then(resetHandleSessionTimeoutPromise)
		.catch(resetHandleSessionTimeoutPromise);
	return mainAras._handleSessionTimeoutPromise;
};

SOAP.prototype.parseResponseHeaders = function SOAP_parseResponseHeaders(xmlhttp, arasableObj) { };

SOAP.prototype.getDateStamp = function SOAP_getDateStamp() {
	var date = new Date();
	var now = date.getFullYear() + '-';
	if (date.getMonth() < 10) {
		now += '0';
	}
	now += date.getMonth() + '-';
	if (date.getDate() < 10) {
		now += '0';
	}
	now += date.getDate() + ' ' +
	date.getHours() + ':' + date.getMinutes() + ':' + date.getSeconds() + ':' + date.getMilliseconds();
	return now;
};

///////////////////////////////////////////////////////////////////////////////////////////
// SOAPResults

function SOAPResults(arasableObj, resultsXML, saveChanges) {
	this.arasableObj = arasableObj; //parent aras object

	var xmlWithPermissions;
	if (resultsXML) {
		xmlWithPermissions = setOriginalPermissionID(resultsXML);
		this.results = xmlWithPermissions;
	} else {
		this.results = arasableObj.createXMLDocument();
	}

	//lazy "xmlWithPermissions.xml" calculating to consume memory (mainly) and cpu only when resultsXML is called
	Object.defineProperty(this, 'resultsXML', {
		get: function() {
			return !xmlWithPermissions ? '' : xmlWithPermissions.xml;
		}
	});

	var message = this.getMessage();
	arasableObj.refreshWindows(message, this.results, saveChanges);

	function setOriginalPermissionID(resultsXML) {
		var workDom = arasableObj.createXMLDocument();
		workDom.loadXML(resultsXML);
		//select all nodes "permission_id"
		var permissionNodes = workDom.selectNodes('//permission_id');

		if (permissionNodes && permissionNodes.length > 0) {
			for (var i = 0; i < permissionNodes.length; i++) {
				if (permissionNodes[i].selectSingleNode('./Item') === null) {
					//if it doesn't contain any child nodes - set attribute origPermission = innerText
					permissionNodes[i].setAttribute('origPermission', permissionNodes[i].text);
				} else {
					//else select id of child Item node and set attribute origPermission = id
					permissionNodes[i].setAttribute('origPermission', permissionNodes[i].selectSingleNode('./Item/@id').value);
				}
			}
		}
		return workDom;
	}
}

SOAPResults.prototype.getResponseText = function() {
	return this.resultsXML;
};

SOAPResults.prototype.getParseError = function() {
	var res;
	if (this.results.parseError.errorCode !== 0) {
		res = '*** Wrong SOAP message! *** ' + '\n\n' +
			'Error: ' + this.results.parseError.srcText.replace('H1', 'H3') + '\n' +
			'ErrorCode: ' + this.results.parseError.errorCode + '\n' +
			'Reason: ' + this.results.parseError.reason;
	} else {
		res = undefined;
	}

	return res;
};

SOAPResults.prototype.isFault = function SOAPResults_isFault() {
	if (this.results.parseError.errorCode !== 0) {
		return this.getParseError();
	}

	var fault = this.results.selectSingleNode(TopWindowHelper.getMostTopWindowWithAras(window).aras.XPathFault());
	if (fault) {
		return true;
	} else {
		return false;
	}
};

SOAPResults.prototype.getFaultCode = function() {
	if (this.results.parseError.errorCode !== 0) {
		return this.getParseError();
	}

	var faultcode = this.results.selectSingleNode(TopWindowHelper.getMostTopWindowWithAras(window).aras.XPathFault('/faultcode'));
	if (faultcode) {
		return faultcode.text;
	} else {
		return 0;
	}
};

SOAPResults.prototype.getFaultString = function() {
	if (this.results.parseError.errorCode !== 0) {
		return this.getParseError();
	}

	var faultstring = this.results.selectSingleNode(TopWindowHelper.getMostTopWindowWithAras(window).aras.XPathFault('/faultstring'));
	if (faultstring) {
		return faultstring.text;
	} else {
		return '';
	}
};

SOAPResults.prototype.getFaultActor = function() {
	if (this.results.parseError.errorCode !== 0) {
		return this.getParseError();
	}

	var faultactor = this.results.selectSingleNode(TopWindowHelper.getMostTopWindowWithAras(window).aras.XPathFault('/detail/legacy_faultactor'));
	if (faultactor) {
		return faultactor.text;
	} else {
		return '';
	}
};

SOAPResults.prototype.getFaultDetails = function() {
	if (this.results.parseError.errorCode !== 0) {
		return this.getParseError();
	}

	var detail = this.results.selectSingleNode(TopWindowHelper.getMostTopWindowWithAras(window).aras.XPathFault('/detail'));
	var msg = '';
	if (detail) {
		msg = detail.text; //.replace(/^.+\]/,'');
		//    msg = msg.replace(/,.+$/,'');
	}
	return msg;
};

SOAPResults.prototype.getServerMessage = function SOAPResults_getServerMessage() {
	var faultNd = this.results.selectSingleNode(TopWindowHelper.getMostTopWindowWithAras(window).aras.XPathFault());
	if (faultNd && faultNd.parentNode) {
		var serverMessageNd = faultNd.parentNode.selectSingleNode('server_message');
		if (serverMessageNd) {
			return serverMessageNd.xml;
		}
	}
};

SOAPResults.prototype.getResultsBody = function() {
	var res = this.getResult();
	var items = res.selectNodes('Item');
	return items.length == 1 ? items[0].xml : res.xml;
};

SOAPResults.prototype.getResult = function() {
	var res = null;
	if (this.results && this.results.documentElement) {
		res = this.results.selectSingleNode(TopWindowHelper.getMostTopWindowWithAras(window).aras.XPathResult());
	}

	if (!res) {
		var subst = this.arasableObj.createXMLDocument();
		subst.loadXML(SoapConstants.EnvelopeBodyStart + '<Result />' + SoapConstants.EnvelopeBodyEnd);
		res = subst.documentElement.selectSingleNode(TopWindowHelper.getMostTopWindowWithAras(window).aras.XPathResult());
	}

	return res;
};

SOAPResults.prototype.getMessage = function() {
	var res = null;
	if (this.results && this.results.documentElement) {
		res = this.results.selectSingleNode(TopWindowHelper.getMostTopWindowWithAras(window).aras.XPathMessage());
	}

	if (!res) {
		var subst = new XmlDocument();
		subst.loadXML(SoapConstants.EnvelopeBodyStart + '<Message />' + SoapConstants.EnvelopeBodyEnd);
		res = subst.documentElement.selectSingleNode(TopWindowHelper.getMostTopWindowWithAras(window).aras.XPathMessage());
	}

	return res;
};

SOAPResults.prototype.getMessageValue = function SOAPResults_getMessageValue(key) {
	var msg;
	if (this.isFault()) {
		msg = this.results.selectSingleNode(TopWindowHelper.getMostTopWindowWithAras(window).aras.XPathFault('/detail/message[@key=\'' + key + '\']'));
	} else {
		var nd = this.getMessage();
		if (nd) {
			msg = nd.selectSingleNode('event[@name=\'' + key + '\']');
		}
	}

	return (msg ? msg.getAttribute('value') : undefined);
};

/** ..\Modules\aras.innovator.core.Core\Scripts\Classes\DragHelper.js **/
var DragAndDrop;
(function(DragAndDrop) {
	var DragEventHelper = (function() {
		function DragEventHelper(element) {
			this.element = element;
			this.dragTimers = [];
			this.dragEnterHandlers = [];
			this.dragLeaveHandlers = [];

			this.onDragEnter = this.onDragEnter.bind(this);
			this.onDragLeave = this.onDragLeave.bind(this);
			this.onDragOver = this.onDragOver.bind(this);
			this.onDrop = this.onDrop.bind(this);
			element.addEventListener('dragenter', this.onDragEnter, false);
			element.addEventListener('dragleave', this.onDragLeave, false);
			element.addEventListener('dragover', this.onDragOver, false);
			element.addEventListener('drop', this.onDrop, false);
		}
		DragEventHelper.prototype.addDragEnterListener = function(handler) {
			this.dragEnterHandlers.push(handler);
		};

		DragEventHelper.prototype.addDragLeaveListener = function(handler) {
			this.dragLeaveHandlers.push(handler);
		};

		DragEventHelper.prototype.removeListeners = function() {
			this.dragEnterHandlers = [];
			this.dragLeaveHandlers = [];
			this.element.removeEventListener('dragenter', this.onDragEnter);
			this.element.removeEventListener('dragleave', this.onDragLeave);
			this.element.removeEventListener('dragover', this.onDragOver);
			this.element.removeEventListener('drop', this.onDrop);
		};

		DragEventHelper.prototype.onDragEnter = function(e) {
			var _this = this;
			setTimeout(function() {
				var timers = _this.dragTimers;
				_this.dragTimers = [];
				for (var i = 0; i < timers.length; i++) {
					clearTimeout(timers[i]);
				}
			}, 0);
			if (!this.dragStarted) {
				this.dragStarted = true;
				this.dragEnterHandlers.forEach(function(handler) {
					handler(e);
				});
			}
			this.stopEvent(e);
			return false;
		};

		DragEventHelper.prototype.onDragLeave = function(e) {
			var _this = this;
			var dragTimer = setTimeout(function() {
				_this.dragStarted = false;
				_this.dragLeaveHandlers.forEach(function(handler) {
					handler(e);
				});
			}, 100);
			this.dragTimers.push(dragTimer);
			this.stopEvent(e);
			return false;
		};

		DragEventHelper.prototype.onDragOver = function(e) {
			if (e.dataTransfer && e.dataTransfer.dropEffect) {
				e.dataTransfer.dropEffect = 'none';
			}
			this.stopEvent(e);
			return false;
		};

		DragEventHelper.prototype.onDrop = function(e) {
			this.dragStarted = false;
			this.dragLeaveHandlers.forEach(function(handler) {
				handler(e);
			});
			this.stopEvent(e);
			return false;
		};

		DragEventHelper.prototype.stopEvent = function(e) {
			if (e.preventDefault) {
				e.preventDefault();
			}
			if (e.stopPropagation) {
				e.stopPropagation();
			}
		};
		return DragEventHelper;
	})();
	DragAndDrop.DragEventHelper = DragEventHelper;
})(DragAndDrop || (DragAndDrop = {}));

/** ..\Modules\aras.innovator.core.Core\Scripts\Classes\DragManager.js **/
var DragAndDrop;
(function(DragAndDrop) {
	var DragManager = (function() {
		function DragManager(win) {
			if (typeof win === 'undefined') { win = window; }
			this.win = win;
			this.childs = [];
			this.dropboxes = [];
			this.dragHelper = new DragAndDrop.DragEventHelper(win);
			this.onDragHandler = this.onDragHandler.bind(this);
			this.dragHelper.addDragEnterListener(this.onDragHandler);
			this.dragHelper.addDragLeaveListener(this.onDragHandler);

			this.eventAggregator = new DragEventAggregator();
			this.onGlobalDragEnterHandler = this.onGlobalDragEnterHandler.bind(this);
			this.onGlobalDragLeaveHandler = this.onGlobalDragLeaveHandler.bind(this);
			this.eventAggregator.addDragEnterListener(this.onGlobalDragEnterHandler);
			this.eventAggregator.addDragLeaveListener(this.onGlobalDragLeaveHandler);

			try {
				if (win.parent.dragManager) {
					this.parent = win.parent.dragManager;
					this.parent.addChildManager(this);
				}
			} catch (ex) {
				this.parent = null;
			}
		}
		DragManager.prototype.deinit = function() {
			if (this.parent) {
				this.parent.removeChildManager(this);
				this.parent = null;
			}
			this.dragHelper.removeListeners();
			this.dragHelper = null;
			this.eventAggregator.removeListeners();
			this.eventAggregator = null;
		};

		DragManager.prototype.addDropbox = function(dropbox) {
			this.dropboxes.push(dropbox);
		};

		DragManager.prototype.removeDropbox = function(dropbox) {
			var index = this.dropboxes.indexOf(dropbox);
			if (index > -1) {
				this.dropboxes.splice(index, 1);
			}
		};

		DragManager.prototype.addChildManager = function(child) {
			this.childs.push(child);
		};

		DragManager.prototype.removeChildManager = function(child) {
			var index = this.childs.indexOf(child);
			if (index > -1) {
				this.childs.splice(index, 1);
			}
		};

		DragManager.prototype.onDragHandler = function(e) {
			var topManager = this.findTopManager();
			topManager.eventAggregator.onDrag(e);
		};

		DragManager.prototype.onGlobalDragEnterHandler = function(e) {
			var maxLevels = [];
			this.childs.forEach(function(child) {
				var levels = [];
				child.dropboxes.forEach(function(dropbox) {
					if (dropbox.dropPriority > 0) {
						levels.push(dropbox.dropPriority);
					}
				});
				if (levels.length > 0) {
					var maxLevel = Math.max.apply(null, levels);
					if (maxLevel) {
						maxLevels.push(maxLevel);
					}
				}
			});
			this.traverseManagers(function(manager) {
				var maxPriority = Math.max.apply(null, maxLevels);
				manager.dropboxes.forEach(function(dropbox) {
					if (maxLevels.length > 0) {
						if (dropbox.dropPriority === maxPriority) {
							dropbox.onDragBrowserEnter(e);
						}
					} else {
						dropbox.onDragBrowserEnter(e);
					}
				});
			});
		};

		DragManager.prototype.onGlobalDragLeaveHandler = function(e) {
			this.traverseManagers(function(manager) {
				manager.dropboxes.forEach(function(dropbox) {
					dropbox.onDragBrowserLeave(e);
				});
			});
		};

		DragManager.prototype.traverseManagers = function(callback) {
			callback(this);
			this.childs.forEach(function(child) {
				try {
					child.traverseManagers(callback);
				} catch (ex) {
					console.error(ex);
				}
			});
		};

		DragManager.prototype.findTopManager = function() {
			var topManager = this;
			var parent = this.parent;
			while (parent) {
				topManager = parent;
				parent = topManager.parent;
			}
			return topManager;
		};
		return DragManager;
	})();
	DragAndDrop.DragManager = DragManager;

	var DragEventAggregator = (function() {
		function DragEventAggregator() {
			this.status = 0;
			this.dragEnterHandlers = [];
			this.dragLeaveHandlers = [];
		}
		DragEventAggregator.prototype.addDragEnterListener = function(handler) {
			this.dragEnterHandlers.push(handler);
		};

		DragEventAggregator.prototype.addDragLeaveListener = function(handler) {
			this.dragLeaveHandlers.push(handler);
		};

		DragEventAggregator.prototype.removeListeners = function() {
			this.dragEnterHandlers = [];
			this.dragLeaveHandlers = [];
		};

		DragEventAggregator.prototype.onDrag = function(e) {
			switch (e.type) {
				case 'dragenter':
					this.onDragEnter(e);
					break;
				case 'dragleave':
					this.onDragLeave(e);
					break;
				case 'drop':
					this.onDrop(e);
					break;
				default:
					break;
			}
		};

		DragEventAggregator.prototype.onDragEnter = function(e) {
			if (this.status === 0) {
				this.dragEnterHandlers.forEach(function(handler) {
					handler(e);
				});
			}
			this.status++;
		};

		DragEventAggregator.prototype.onDragLeave = function(e) {
			this.status--;
			if (this.status <= 0) {
				this.status = 0;
				this.dragLeaveHandlers.forEach(function(handler) {
					handler(e);
				});
			}
		};

		DragEventAggregator.prototype.onDrop = function(e) {
			this.status = 0;
			this.dragLeaveHandlers.forEach(function(handler) {
				handler(e);
			});
		};
		return DragEventAggregator;
	})();
	DragAndDrop.DragEventAggregator = DragEventAggregator;
})(DragAndDrop || (DragAndDrop = {}));

window.dragManager = window.dragManager || new DragAndDrop.DragManager(window);
window.addEventListener('beforeunload', function() {
	if (window.dragManager) {
		window.dragManager.deinit();
		delete window.dragManager;
	}
});

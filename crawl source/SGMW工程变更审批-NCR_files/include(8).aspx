
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

/** PopupMenu.js **/
// © Copyright by Aras Corporation, 2004-2007.

//constants
var fontSizeConst = '8';
var popupMenuFontConst = 'normal normal normal ' + fontSizeConst + 'pt normal';
var borderWidthConst = 2;
var leftRightMarginConst = 0;
var topBottomMarginConst = 1;
var labelHeightConst = 13;
var arasScrollBarConst = 15;
var separatorImgPathConst = '../imagesLegacy/100x4_divider.gif';

function setSeparatorImgPath(newPath) {
	separatorImgPathConst = newPath;
}

// ++++++++++   PopupMenu   ++++++++++ //
function PopupMenu(menuID, menuLabel, showLabel) {
	if (menuID === undefined) {
		menuID = 'id_';
	}
	if (menuLabel === undefined) {
		menuLabel = '';
	} else {
		menuLabel = menuLabel.toString();
	}
	if (showLabel === undefined) {
		showLabel = false;
	}

	this.isMenu = true;

	this.id = menuID;
	this.label = menuLabel;
	this.showLabel = showLabel;
	this.onClick = null;
	this.font = popupMenuFontConst;
	this.win = window;

	this.contentArr = [];
	this.contentMap = {};
	this.submenus = {};

	this.isShown = false;
	this.parentMenu = null;
	this.shownSubMenu = null;
	this.clickedID = '';
	this.enabled = true;

	this.oPopup = null;

	this.topVar = 0;
	this.left = 0;
	this.width = 0;
	this.height = 0;
}

PopupMenu.prototype.isOpen = function PopupMenuIsOpen() {
	if (this.oPopup === null) {
		return false;
	}
	return this.oPopup.isOpen;
};

PopupMenu.prototype.setLabel = function PopupMenuSetLabel(menuLabel) {
	if (menuLabel === undefined) {
		return;
	}
	this.label = menuLabel.toString();
};

PopupMenu.prototype.setShowLabel = function PopupMenuSetLabel(showLabel) {
	if (showLabel === undefined) {
		return;
	}
	this.showLabel = showLabel;
};

PopupMenu.prototype.setOnClick = function PopupMenuSetOnClick(onClickHandler) {
	if (!onClickHandler || typeof (onClickHandler) != 'function') {
		return;
	}

	this.onClick = onClickHandler;
};

PopupMenu.prototype.setFont = function PopupMenuSetFont(newFont) {
	if (!newFont) {
		return;
	}
	this.font = newFont;
};

PopupMenu.prototype.setParentWindow = function PopupMenuSetParentWindow(win) {
	if (!win) {
		return;
	}
	this.win = win;
};

PopupMenu.prototype.setEnabled = function PopupMenuSetEnabled(enabled) {
	this.enabled = enabled;
};

PopupMenu.prototype.getId = function PopupMenuGetId() {
	return this.id;
};

PopupMenu.prototype.getLabel = function PopupMenuGetLabel() {
	return this.label;
};

PopupMenu.prototype.getShowLabel = function PopupMenuGetLabel() {
	return this.showLabel;
};

PopupMenu.prototype.getOnClick = function PopupMenuGetOnClick() {
	return this.onClick;
};

PopupMenu.prototype.getFont = function PopupMenuGetFont() {
	return this.font;
};

PopupMenu.prototype.getParentWindow = function PopupMenuGetParentWindow() {
	return this.win;
};

PopupMenu.prototype.isEnabled = function PopupMenuIsEnabled() {
	return this.enabled;
};

PopupMenu.prototype.setClickedID = function PopupMenuSetClickedID(clickedID) {
	if (!clickedID) {
		return;
	}
	this.clickedID = clickedID;
	if (this.contentMap[clickedID] && this.contentMap[clickedID].isCheckable) {
		var prevState = this.contentMap[clickedID].isChecked();
		this.contentMap[clickedID].setChecked(!prevState);
	}
	if (!this.onClick && this.parentMenu) {
		return this.parentMenu.setClickedID(clickedID);
	}

	this.hideAll();

	if (this.onClick) {
		this.onClick(this.getItemById(clickedID));
	}
};

PopupMenu.prototype.getClickedID = function PopupMenuGetClickedID() {
	return this.clickedID;
};

PopupMenu.prototype.getSeparator = function() {
	return '<div style="border-top:solid #808080 1px; border-bottom:solid #ffffff 1px; margin-left:2px; margin-right:2px;"></div>';
};

PopupMenu.prototype.show = function PopupMenuShow(left, topVar) {
	if (!('createPopup' in this.win)) {
		return;
	}
	if (this.contentArr.length === 0) {
		return; //to not show empty menu
	}

	if (left === undefined) {
		left = 0;
	}
	if (topVar === undefined) {
		topVar = 0;
	}

	if (this.isShown) {
		return true;
	}

	this.win.oPopup = this.win.createPopup();
	this.oPopup = this.win.oPopup;
	var oPopup = this.oPopup;

	var i;
	var itm;
	var field;

	var doc = oPopup.document.open();
	var font = this.getFont();

	doc.writeln('<html>\n' +
		'<head><style type="text/css">\n' +
		'body {overflow-y: hidden; overflow-x: hidden; border-style:outset; border-color:grey; ' +
		'	cursor:default; background-color:buttonface;' +
		'	border-width:' + borderWidthConst + '; ' +
		'	margin-top:' + topBottomMarginConst + '; ' +
		'	margin-bottom:' + topBottomMarginConst + '; ' +
		'	margin-left:' + leftRightMarginConst + '; ' +
		'	margin-right:' + leftRightMarginConst + '; ' +
		'	font:' + (font ? font : '') + '; ' +
		'	font-family:Tahoma; ' +
		'	scrollbar-3dlight-color:buttonface;\n' +
		'}\n' +
		'table {font:' + (font ? font : '') + '; font-family:Tahoma; ' +
		'	width:100%; height:' + (fontSizeConst * 2.5) + 'px;' +
		'}\n' +
		'span {float:none; width:100%;}\n' +
		'.st {color:; background-color:;}\n' +
		'.sth {color:highlighttext; background-color:highlight;}\n' +
		'.labelTD {width:100%;}\n' +
		'.csignZone {font-family:Marlett; font-size:x-small; margin-right:0.1em; visibility:hidden; }\n' +//border:solid red 1px;
		'.labelZone {margin-right:2em;}\n' +//border:solid green 1px;
		'.smsignZone {font-family:Marlett; font-size:x-small; margin-right:0.1em;}\n' +//border:solid blue 1px;
		'</style></head>\n');

	doc.creatorOwner = this;

	//+++ define the very first and very last non separator rows +++
	var firstRowId = '';
	var lastRowId = '';
	var cntArr = this.contentArr;
	if (cntArr && cntArr.length > 0) {
		i = 0;
		do {
			firstRowId = (cntArr[i].getId) ? cntArr[i].getId() : '';
			i++;
		} while (!firstRowId && i < cntArr.length);
		i = cntArr.length - 1;
		do {
			lastRowId = (cntArr[i].getId) ? cntArr[i].getId() : '';
			i--;
		} while (!lastRowId && i >= 0);
	}
	//--- define the very first and very last non separator rows ---

	doc.writeln('<script>\n' +

	'function getSpanElement(elem) {\n' +
	' if (elem.tagName=="SPAN") return elem;\n' +
	' if (elem.tagName=="BODY") return null;\n' +
	' if (!elem.parentElement) return null;\n' +
	'	return getSpanElement(elem.parentElement);\n' +
	'}\n' +

	'var highlightedRow = null;\n' +
	'displayArasScrollBar = false;\n' +
	'var firstRowId = "' + firstRowId + '";\n' +
	'var lastRowId = "' + lastRowId + '";\n' +

	'var maxScrollTop = null;\n' +
	'function setHighLighted(row) {\n' +
	'	if (row === highlightedRow) return;\n' +
	'	if (highlightedRow && highlightedRow.id==firstRowId && row.id==lastRowId && ' + this.contentArr.length + '>2) return;\n' +
	'	if (highlightedRow && highlightedRow.id==lastRowId && row.id==firstRowId && ' + this.contentArr.length + '>2) return;\n' +
	'	if (highlightedRow) {\n' +
	'		if (document.creatorOwner.getItemById(highlightedRow.id).isEnabled()) highlightedRow.className = "st";\n' +
	'		else highlightedRow.className = "std";\n' +
	'	}\n' +
	'	if (document.creatorOwner.getItemById(row.id).isEnabled()) row.className = "sth";\n' +
	'	else row.className = "sthd";\n' +
	'	highlightedRow = row;\n' +
	'	if (row.id==firstRowId || row.id==lastRowId) bMousePressedDown=false;\n' +
	'	var docB = document.getElementById("mainDiv"); \n' +
	'	var iOffsetTop = row.offsetTop;\n' +
	'	var iClientHeight = row.clientHeight;\n' +
	'	var st=docB.scrollTop;\n' +
	'	if (iOffsetTop - st<=0) docB.scrollTop = iOffsetTop;\n' +
	'	if (iOffsetTop + iClientHeight - docB.clientHeight - st>5) docB.scrollTop = st+iClientHeight;\n' +
	'	if (row.id==lastRowId) maxScrollTop = docB.scrollTop;\n' +
	'	document.all("UpArrowButton").disabled = (docB.scrollTop === 0 ? true : false);\n' +
	'	document.all("DownArrowButton").disabled = ((maxScrollTop!==null && maxScrollTop<=docB.scrollTop) ? true : false);\n' +
	'}\n' +

	'var bMousePressedDown=false;\n' +
	'function upDownArrowButtonClick(isUp)' +
	'{\n' +
	'	var kCode = (isUp) ? 38 : 40;\n' +
	'	if (bMousePressedDown) onKeyPress({keyCode:kCode});\n' +
	'	if (bMousePressedDown) setTimeout("upDownArrowButtonClick("+isUp+")", 100);\n' +
	'}\n' +

	'function showSubMenu(row) {\n' +
	'	var docB = document.getElementById("mainDiv"); \n' +
	'	var left = document.creatorOwner.width;\n' +
	'	var topVar = row.offsetTop + ' + (borderWidthConst + topBottomMarginConst) + '+' + (this.showLabel ? labelHeightConst : '0') +
	'+(document.displayArasScrollBar?(' + arasScrollBarConst + '):0) - docB.scrollTop;\n' +
	'	document.creatorOwner.showSubMenu(row.id, left, topVar);\n' +
	'}\n' +

	'document.onselectionchange = function () {return false;}\n' +

	'function onMouseOverRow(row) {\n' +
	'	if (row === highlightedRow) return;\n' +
	'	setHighLighted(row);\n' +
	'	if (row.clss == "submenu") showSubMenu(row);\n' +
	'	else document.creatorOwner.highlightItem(row.id);\n' +
	'}\n' +

	'function onClick(row) {\n' +
	'	if (row.clss == "menuitem") {\n' +
	'		document.creatorOwner.setClickedID(row.id);\n' +
	'	}\n' +
	'	else if (row.clss == "submenu") {\n' +
	'		if (document.creatorOwner.shownSubMenu) document.creatorOwner.hideSubMenu();\n' +
	'		else showSubMenu(row);\n' +
	'	}\n' +
	'}\n' +

	'function onKeyPress(event) {\n' +
	'	var keyCode = event.keyCode;\n' +
	'	if (keyCode == 27) {\n' +
	'		document.creatorOwner.hideAll();\n' +
	'	}\n' +
	'	else if (keyCode == 13) {\n' +
	'		if (highlightedRow) {\n' +
	'			if (highlightedRow.clss == "menuitem") {\n' +
	'				document.creatorOwner.setClickedID(highlightedRow.id);\n' +
	'			}\n' +
	'			else if (highlightedRow.clss) {\n' +
	'				if (document.creatorOwner.shownSubMenu) document.creatorOwner.hideSubMenu();\n' +
	'				else showSubMenu(highlightedRow);\n' +
	'			}\n' +
	'		}\n' +
	'	}\n' +
	'	else if (keyCode == 40) {\n' +//down arrow
	'		var nextRow = null;\n' +
	'		if (highlightedRow) nextRow = highlightedRow.nextSibling;\n' +
	'		else {\n' +
	'			var tables = document.all("mainTable").getElementsByTagName("TABLE");\n' +
	'			if (tables && tables.length>0) nextRow = tables(0);\n' +
	'		}\n' +
	'		if (nextRow) for( ; nextRow.tagName!="TABLE" || nextRow.disabled==true; ) {\n' +
	'			nextRow = nextRow.nextSibling;\n' +
	'			if (!nextRow) break;\n' +
	'		}\n' +

	'		if (!nextRow || nextRow.tagName!="TABLE" || nextRow.disabled) { \n' +
	'			var tables = document.all("mainTable").getElementsByTagName("TABLE");\n' +
	'			if (tables && tables.length>0) nextRow = tables(0);\n' +
	'		}\n' +
	'		if (nextRow) for( ; nextRow.tagName!="TABLE" || nextRow.disabled==true; ) {\n' +
	'			nextRow = nextRow.nextSibling;\n' +
	'			if (!nextRow) break;\n' +
	'		}\n' +
	'		if (!nextRow || nextRow.tagName!="TABLE" || nextRow.disabled) nextRow = null;\n' +

	'		if (nextRow) setHighLighted(nextRow);\n' +
	'	}\n' +
	'	else if (keyCode == 39) {\n' +//right arrow
	'		if (highlightedRow && highlightedRow.clss == "submenu") showSubMenu(highlightedRow);\n' +
	'	}\n' +
	'	else if (keyCode == 38) {\n' +//up arrow
	'	var prevRow = null;\n' +
	'	if (highlightedRow) prevRow = highlightedRow.previousSibling;\n' +
	'	else {\n' +
	'		var tables = document.all("mainTable").getElementsByTagName("TABLE");\n' +
	'		if (tables && tables.length>0) prevRow = tables(tables.length-1);\n' +
	'	}\n' +
	'	if (prevRow) for( ; prevRow.tagName!="TABLE" || prevRow.disabled==true; ) {\n' +
	'		prevRow = prevRow.previousSibling;\n' +
	'		if (!prevRow) break;\n' +
	'	}\n' +

	'	if (!prevRow || prevRow.tagName!="TABLE" || prevRow.disabled) {\n' +
	'		var tables = document.all("mainTable").getElementsByTagName("TABLE");\n' +
	'		if (tables && tables.length>0) prevRow = tables(tables.length-1);\n' +
	'	}\n' +
	'	if (prevRow) for( ; prevRow.tagName!="TABLE" || prevRow.disabled==true; ) {\n' +
	'		prevRow = prevRow.previousSibling;\n' +
	'		if (!prevRow) break;\n' +
	'	}\n' +

	'	if (!prevRow || prevRow.tagName!="TABLE" || prevRow.disabled) prevRow = null;\n' +
	'		if (prevRow) setHighLighted(prevRow);\n' +
	'	}\n' +
	'	else if (keyCode == 37) {\n' +//left arrow
	'		if (document.creatorOwner.parentMenu) document.creatorOwner.hide();\n' +
	'	}\n' +
	'}\n' +
	'</script>\n' +

	'<body ' +
	'oncontextmenu="return false;" ondblclick="return false;" onselectstart="return false;"' +
	'onkeydown="onKeyPress(event); return false;" ' +
	'onunload="document.creatorOwner.hideAll();" ' +
	'>');

	if (this.showLabel) {
		var label2display = this.getLabel().replace(/ /g, '&nbsp;');
		doc.writeln('<center><span id="labelSpan" align="center">&nbsp;&nbsp;' + label2display + '&nbsp;&nbsp;</span></center>');
		doc.writeln(this.getSeparator());
	}

	var expressionFunctionCode = '';

	doc.writeln('<center><span id="UpArrow" class="smsignZone" style="cursor:pointer;" onmouseover="bMousePressedDown=true; upDownArrowButtonClick(true);"' +
				' onmouseout="bMousePressedDown=false;">' +
				'<button id="UpArrowButton" DISABLED class="smsignZone" style="background-color:buttonface; width:expression(document.body.clientWidth);' +
				' cursor:pointer; border:none;">&#53;</button></span></center>');

	expressionFunctionCode += '' +
		'var field = document.getElementById(\'UpArrow\');\r\n' +
		'field.style[\'display\'] = displayArasScrollBar ? \'block\' : \'none\';\r\n';

	doc.writeln('<div id="mainDiv" width="100%" style="overflow:hidden; ">' +
			'<table id="mainTable" cellspacing="0" cellpadding="0" border="0"><tr><td nowrap valign="middle">');

	expressionFunctionCode += '' +
			'var field = document.getElementById(\'mainDiv\');\r\n' +
			'field.style[\'height\'] = document.body.clientHeight-(displayArasScrollBar? (2*' + arasScrollBarConst + '):0)';
	if (this.showLabel) {
		expressionFunctionCode += '-document.all(\'labelSpan\').offsetHeight';
	}

	expressionFunctionCode += ';\r\n';

	var const1 = '<font style="visibility:hidden" face="Marlett" size="1">&#97;</font>';
	var const2 = '<font face="Marlett"  size="1">&#97;</font>';

	for (i = 0; i < this.contentArr.length; i++) {
		itm = this.contentArr[i];
		if (itm.isSeparator) {
			doc.write(this.getSeparator());
		} else {
			var str =
			'<table clss="' + (itm.isMenu ? 'submenu' : 'menuitem') + '" id="' + itm.getId().toString().replace(/"/g, '&quot;') +
			'" onmouseover="onMouseOverRow(this); return false;" ' +
			'onclick="onClick(this); return false;" cellpadding="0" cellspacing="0" border="0"><tr>' +
			'<td align="left" valign="middle"><span class="csignZone" ' +
			((!itm.isMenu && itm.isChecked()) ? 'style="visibility:visible;"' : '') + '>&#97;</span></td>' +
			'<td align="left" valign="middle" class="labelTD" nowrap><span class="labelZone">' + itm.getLabel() + '</span></td>' +
			(itm.isMenu ? '<td align="left" valign="middle"><span class="smsignZone">&#52;</span></td>' : '') +
			'</tr></table>';

			doc.write(str);
		}
	}

	doc.writeln('<script>\n var elem = null;');
	for (i = 0; i < this.contentArr.length; i++) {
		itm = this.contentArr[i];
		if (!itm.isSeparator && !itm.isEnabled()) {
			doc.writeln(
				'elem = document.getElementById("' + itm.getId() + '");\n' +
				'if (elem && !elem.length) elem.disabled = true;'
			);
		}
	}
	doc.writeln('</script>');

	doc.writeln('</td></tr></table></div>');
	doc.writeln('<center><span id="DownArrow" class="smsignZone" style="cursor:pointer;" onmouseover="bMousePressedDown=true; upDownArrowButtonClick(false);"' +
				'onmouseout="bMousePressedDown=false;"><button id="DownArrowButton" class="smsignZone" style="background-color:buttonface;' +
				' width:expression(document.body.clientWidth); cursor:pointer; border:none;">&#54;</button></span></center>');
	expressionFunctionCode += '' +
	'var field = document.getElementById(\'DownArrow\');\r\n' +
	'field.style[\'display\'] = displayArasScrollBar ? \'block\' : \'none\';\r\n';

	var content = '<script type="text/javascript">';
	content += 'function expression_PopupMenu_setExpression(displayArasScrollBar)\r\n{\r\n' + expressionFunctionCode + '}\r\n';
	content += 'expression_PopupMenu_setExpression(document.displayArasScrollBar);';
	content += '</script>';

	doc.writeln(content);

	doc.writeln('</body></html>');
	doc.close();

	this.isShown = true;
	oPopup.show(left, topVar, 1, 1, this.win.document.body);
	var w1 = doc.all('mainTable').offsetWidth;
	var w2 = (this.showLabel ? doc.all('labelSpan').offsetWidth : 0);
	var width = ((w1 - w2 < 0) ? w2 : w1) + 2 * borderWidthConst + 2 * leftRightMarginConst;
	var height = doc.all('mainTable').offsetHeight + 2 * borderWidthConst + 2 * topBottomMarginConst + (this.showLabel ? doc.all('labelSpan').offsetHeight : 0);

	var maxHeight = window.screen.availHeight;
	this.left = left;
	this.topVar = topVar;
	this.width = width;
	this.height = (height - maxHeight <= 0) ? height : maxHeight;
	document.displayArasScrollBar = (height - maxHeight <= 0) ? false : true;

	field = oPopup.document.getElementById('UpArrow');
	field.style.display = oPopup.document.displayArasScrollBar ? 'block' : 'none';

	field = oPopup.document.getElementById('mainDiv');
	var newHeight = document.body.clientHeight - (document.displayArasScrollBar ? (2 * arasScrollBarConst) : 0);

	if (this.showLabel) {
		newHeight -= oPopup.document.all('labelSpan').offsetHeight;
	}
	field.style.height = newHeight;

	field = oPopup.document.getElementById('DownArrow');
	field.style.display = oPopup.document.displayArasScrollBar ? 'block' : 'none';

	oPopup.show(this.left, this.topVar, this.width, this.height, this.win.document.body);
	return true;
};

PopupMenu.prototype.highlightItem = function PopupMenuHighlightItem(menuitemID) {
	var submenu = this.submenus[menuitemID];
	if (this.shownSubMenu && (!submenu || this.shownSubMenu !== submenu)) {
		this.hideSubMenu();
	}
};

PopupMenu.prototype.showSubMenu = function PopupMenuShowSubMenu(submenuID, left, topVar) {
	var submenu = this.submenus[submenuID];
	if (!submenu) {
		return false;
	}
	if (this.shownSubMenu === submenu) {
		return true;
	}

	if (this.shownSubMenu) {
		this.hideSubMenu();
	}

	submenu.setParentWindow(this.oPopup.document.parentWindow);
	submenu.show(left, topVar);
	this.shownSubMenu = submenu;
	return true;
};

PopupMenu.prototype.hideSubMenu = function PopupMenuHideSubMenu() {
	if (!this.shownSubMenu) {
		return false;
	}

	this.shownSubMenu.hide();
	this.shownSubMenu = null;
};

PopupMenu.prototype.hide = function PopupMenuHide() {
	if (!this.isShown) {
		return true;
	}

	if (this.shownSubMenu) {
		this.shownSubMenu.hide();
	}
	if (this.parentMenu && this.parentMenu.shownSubMenu === this) {
		this.parentMenu.shownSubMenu = null;
	}

	this.oPopup.document.body.onunload = '';
	this.oPopup.hide();

	this.isShown = false;
	return true;
};

PopupMenu.prototype.hideAll = function PopupMenuHideAll(event) {
	if (!this.isShown) {
		return true;
	}

	if (this.parentMenu) {
		this.parentMenu.hideAll();
	} else {
		this.hide();
	}
};

PopupMenu.prototype.getItemCount = function PopupMenuGetItemCount() {
	return this.contentArr.length;
};

PopupMenu.prototype.getItem = function PopupMenuGetItem(pos) {
	var res = this.contentArr[pos];
	if (!res) {
		res = null;
	}
	return res;
};

PopupMenu.prototype.getItemById = function PopupMenuGetItemById(id) {
	var res = this.contentMap[id];
	if (!res) {
		for (var submenuID in this.submenus) {
			res = this.submenus[submenuID].getItemById(id);
			if (res) {
				break;
			}
		}
		if (!res) {
			res = null;
		}
	}

	return res;
};

PopupMenu.prototype.add = function PopupMenuAdd(arg1, arg2, arg3, arg4) {
	return this.insert(this.contentArr.length, arg1, arg2, arg3, arg4);
};

PopupMenu.prototype.addSeparator = function PopupMenuAddSeparator() {
	return this.insertSeparator(this.contentArr.length);
};

PopupMenu.prototype.insert = function(pos, arg2, arg3, arg4, arg5) {
	if (pos === undefined) {
		return null;
	}
	pos = parseInt(pos);
	if (isNaN(pos)) {
		return null;
	}

	if (arguments.length >= 2 && typeof (arg2) == 'object' && arg2.isMenu) {
		return this.insertSubMenu(pos, arg2, arg3);
	} else {
		return this.insertMenuItem(pos, arg2, arg3, arg4, arg5);
	}
};

PopupMenu.prototype.insertSeparator = function PopupMenuInsertSeparator(pos) {
	if (pos === undefined) {
		return null;
	}
	pos = parseInt(pos);
	if (isNaN(pos)) {
		return null;
	}

	var newItm = new MenuSeparator();
	if (!newItm) {
		return null;
	}

	if (pos < 0) {
		pos = 0;
	} else if (pos > this.contentArr.length) {
		pos = this.contentArr.length;
	}

	if (pos == this.contentArr.length) {
		this.contentArr.push(newItm);
	} else if (pos === 0) {
		var tmpArr = new Array(newItm);
		this.contentArr = tmpArr.concat(this.contentArr);
	} else {
		var tmpArr1 = this.contentArr.slice(0, pos);
		var tmpArr2 = this.contentArr.slice(pos);
		tmpArr1.push(newItm);
		this.contentArr = tmpArr1.concat(tmpArr2);
	}

	return newItm;
};

PopupMenu.prototype.insertMenuItem = function PopupMenuMenuItem(pos, pointID, pointLabel, pointEnabled, isCheckable) {
	if (pointID === undefined) {
		pointID = 'id_';
	}
	if (pointLabel === undefined) {
		pointLabel = pointID;
	}
	if (pointEnabled === undefined) {
		pointEnabled = true;
	}
	if (isCheckable === undefined) {
		isCheckable = false;
	}

	var newItm = new MenuItem(pointID, pointLabel, pointEnabled, isCheckable);
	if (!newItm) {
		return null;
	}

	if (this.contentMap[newItm.getId()]) {
		return null;
	}

	if (pos < 0) {
		pos = 0;
	} else if (pos > this.contentArr.length) {
		pos = this.contentArr.length;
	}

	if (pos == this.contentArr.length) {
		this.contentArr.push(newItm);
	} else if (pos === 0) {
		var tmpArr = new Array(newItm);
		this.contentArr = tmpArr.concat(this.contentArr);
	} else {
		var tmpArr1 = this.contentArr.slice(0, pos);
		var tmpArr2 = this.contentArr.slice(pos);
		tmpArr1.push(newItm);
		this.contentArr = tmpArr1.concat(tmpArr2);
	}

	this.contentMap[newItm.getId()] = newItm;

	return newItm;
};

PopupMenu.prototype.insertSubMenu = function PopupMenuInsertSubMenu(pos, subMenu, enabled) {
	if (enabled === undefined) {
		enabled = true;
	}

	if (this.contentMap[subMenu.getId()]) {
		return null;
	}

	if (pos < 0) {
		pos = 0;
	} else if (pos > this.contentArr.length) {
		pos = this.contentArr.length;
	}

	if (pos == this.contentArr.length) {
		this.contentArr.push(subMenu);
	} else if (pos === 0) {
		var tmpArr = new Array(subMenu);
		this.contentArr = tmpArr.concat(this.contentArr);
	} else {
		var tmpArr1 = this.contentArr.slice(0, pos);
		var tmpArr2 = this.contentArr.slice(pos);
		tmpArr1.push(subMenu);
		this.contentArr = tmpArr1.concat(tmpArr2);
	}

	this.submenus[subMenu.getId()] = subMenu;
	this.contentMap[subMenu.getId()] = subMenu;
	subMenu.setEnabled(enabled);
	subMenu.parentMenu = this;
};

PopupMenu.prototype.remove = function PopupMenuRemove(pos) {
	if (pos < 0) {
		return null;
	}
	if (pos >= this.getItemCount()) {
		return null;
	}

	var arasObj = aras;
	if (!arasObj) {
		arasObj = (function getMostTopWindowWithArasForPopupMenu(windowObj) {
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
		}().aras);
	}

	var res = this.contentArr[pos];
	if (res.isSeparator) {
	} else if (res.isMenu) {
		arasObj.deletePropertyFromObject(this.submenus, res.getId());
	} else {
		arasObj.deletePropertyFromObject(this.contentMap, res.getId());
	}

	this.contentArr.splice(pos, 1);
	this.hide();

	return res;
};

PopupMenu.prototype.removeAll = function PopupMenuRemoveAll() {
	this.contentArr = [];
	this.submenus = {};
	this.contentMap = {};

	this.hide();
};
// ----------   PopupMenu   ---------- //

// ********************************************************************* //

// ++++++++++   MenuItem   ++++++++++ //
function MenuItem(id, label, enabled, isCheckable) {
	if (id === undefined) {
		id = 'id_';
	}
	if (label === undefined) {
		label = id;
	}
	if (enabled === undefined) {
		enabled = true;
	}
	if (isCheckable === undefined) {
		isCheckable = false;
	}

	this.isMenuItem = true;

	this.id = id;
	this.label = label.toString();
	this.enabled = enabled;
	this.isCheckable = isCheckable;
	this.checked = false;
}

MenuItem.prototype.setLabel = function MenuItemSetLabel(label) {
	if (label === undefined) {
		return;
	}
	this.label = label.toString();
};

MenuItem.prototype.setEnabled = function MenuItemSetEnabled(enabled) {
	if (enabled === undefined) {
		return;
	}
	this.enabled = enabled;
};

MenuItem.prototype.setChecked = function MenuItemSetChecked(checked) {
	if (checked === undefined) {
		return;
	}
	this.checked = checked;
};

MenuItem.prototype.getId = function MenuItemGetId() {
	return this.id;
};

MenuItem.prototype.getLabel = function MenuItemGetLabel() {
	return this.label;
};

MenuItem.prototype.isEnabled = function MenuItemIsEnabled() {
	return this.enabled;
};

MenuItem.prototype.isChecked = function MenuItemIsChecked() {
	return this.checked;
};
// ----------   MenuItem   ---------- //

// ********************************************************************* //

// ++++++++++   MenuSeparator   ++++++++++ //
function MenuSeparator() {
	this.isSeparator = true;
}
// ----------   MenuSeparator   ---------- //

//++++++ Unit tests ++++++
// To run tests just uncomment this section, include this js file to html page, browse the html page.
/*
  //+++ Commont Section +++
function populateMenu(menu, obj) {
    for (var propID in obj) {
        var point = obj[propID];
        if (point=="separator")
        {
          menu.addSeparator();
        } else if (typeof(point) == 'object') {
            var m = new PopupMenu(propID, propID+'\'s Properties', false);
            populateMenu(m, point);
            menu.add(m);
        }
        else menu.add(propID, point, true);
    }
}

function onPPMClick(menuItm)
{
  var menuID = menuItm.getId();
  alert("Selected menu id is " + menuID);
}
  //--- Commont Section ---

  //+++ Test 01 +++
function test01()
{
    var ppm = new PopupMenu('test01_ppm', '', false);
    setSeparatorImgPath('../imagesLegacy/100x4_divider.gif');
    populatePropsList01(ppm);
    ppm.setOnClick(onPPMClick);
    window.focus();
    ppm.show(300, 300);
}
function populatePropsList01(ppm) {
    var obj = new Object();
    for (var i=0; i<10; i++)
      obj["sep"+i] = "separator";
    for (var i=0; i<50; i++)
    {
        obj[i] = "test01 Menu Item Number " + (i+1);
        var r = i/5;
        if (Math.ceil(r)==Math.floor(r))
          obj["sep2"+i] = "separator";
        r = i/10;
        if (Math.ceil(r)==Math.floor(r))
          obj["submenu"+r] = {p1:"menuItem 1", p2:"menuItem 2", p3:"menuItem 3"};
        r = i/7;
        if (Math.ceil(r)==Math.floor(r))
          obj["submenu2"+r] = {p0:"separator", p1:"menuItem 1", p2:"menuItem 2", p3:"menuItem 3", p4:"separator"};

    }
    for (var i=0; i<10; i++)
      obj["sep3"+i] = "separator";
    populateMenu(ppm, obj);
}
test01();
  //--- Test 01 ---
*/
//------ Unit tests ------

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

/** enumerations.js **/
var Enums = {};

Enums.UrlType = {'None': 0, 'SecurityToken': 1};
Enums.SortType = {'Ascending': 0, 'Descending': 1};
Enums.CheckinManagerFlags = {'None': 0, 'UnlockAfterCheckin': 1};
Enums.CheckoutManagerFlags = {'None': 0, 'UseTransactions': 1};

/** cookie.js **/
//
//  Cookie Functions -- "Night of the Living Cookie" Version (25-Jul-96)
//
//  Written by:  Bill Dortch, hIdaho Design <bdortch@hidaho.com>
//  The following functions are released to the public domain.
//
//  This version takes a more aggressive approach to deleting
//  cookies.  Previous versions set the expiration date to one
//  millisecond prior to the current time; however, this method
//  did not work in Netscape 2.02 (though it does in earlier and
//  later versions), resulting in "zombie" cookies that would not
//  die.  DeleteCookie now sets the expiration date to the earliest
//  usable date (one second into 1970), and sets the cookie's value
//  to null for good measure.
//
//  Also, this version adds optional path and domain parameters to
//  the DeleteCookie function.  If you specify a path and/or domain
//  when creating (setting) a cookie**, you must specify the same
//  path/domain when deleting it, or deletion will not occur.
//
//  The FixCookieDate function must now be called explicitly to
//  correct for the 2.x Mac date bug.  This function should be
//  called *once* after a Date object is created and before it
//  is passed (as an expiration date) to SetCookie.  Because the
//  Mac date bug affects all dates, not just those passed to
//  SetCookie, you might want to make it a habit to call
//  FixCookieDate any time you create a new Date object:
//
//    var theDate = new Date();
//    FixCookieDate (theDate);
//
//  Calling FixCookieDate has no effect on platforms other than
//  the Mac, so there is no need to determine the user's platform
//  prior to calling it.
//
//  This version also incorporates several minor coding improvements.
//
//  **Note that it is possible to set multiple cookies with the same
//  name but different (nested) paths.  For example:
//
//    SetCookie ("color","red",null,"/outer");
//    SetCookie ("color","blue",null,"/outer/inner");
//
//  However, GetCookie cannot distinguish between these and will return
//  the first cookie that matches a given name.  It is therefore
//  recommended that you *not* use the same name for cookies with
//  different paths.  (Bear in mind that there is *always* a path
//  associated with a cookie; if you don't explicitly specify one,
//  the path of the setting document is used.)
//
//  Revision History:
//
//    "Toss Your Cookies" Version (22-Mar-96)
//      - Added FixCookieDate() function to correct for Mac date bug
//
//    "Second Helping" Version (21-Jan-96)
//      - Added path, domain and secure parameters to SetCookie
//      - Replaced home-rolled encode/decode functions with Netscape's
//        new (then) escape and unescape functions
//
//    "Free Cookies" Version (December 95)
//
//
//  For information on the significance of cookie parameters, and
//  and on cookies in general, please refer to the official cookie
//  spec, at:
//
//      http://www.netscape.com/newsref/std/cookie_spec.html
//
//******************************************************************
//
// "Internal" function to return the decoded value of a cookie
//
function getCookieVal(offset) {
	var endstr = document.cookie.indexOf(';', offset);
	if (endstr == -1) {
		endstr = document.cookie.length;
	}
	return unescape(document.cookie.substring(offset, endstr));
}
//
//  Function to correct for 2.x Mac date bug.  Call this function to
//  fix a date object prior to passing it to SetCookie.
//  IMPORTANT:  This function should only be called *once* for
//  any given date object!  See example at the end of this document.
//
function FixCookieDate(date) {
	var base = new Date(0);
	var skew = base.getTime(); // dawn of (Unix) time - should be 0
	if (skew > 0) { // Except on the Mac - ahead of its time
		date.setTime(date.getTime() - skew);
	}
}
//
//  Function to return the value of the cookie specified by "name".
//    name - String object containing the cookie name.
//    returns - String object containing the cookie value, or null if
//      the cookie does not exist.
//
function GetCookie(name) {
	var arg = name + '=';
	var alen = arg.length;
	var clen = document.cookie.length;
	var i = 0;
	while (i < clen) {
		var j = i + alen;
		if (document.cookie.substring(i, j) == arg) {
			return getCookieVal(j);
		}
		i = document.cookie.indexOf(' ', i) + 1;
		if (i === 0) {
			break;
		}
	}
	return null;
}
//
//  Function to create or update a cookie.
//    name - String object containing the cookie name.
//    value - String object containing the cookie value.  May contain
//      any valid string characters.
//    [expires] - Date object containing the expiration data of the cookie.  If
//      omitted or null, expires the cookie at the end of the current session.
//    [path] - String object indicating the path for which the cookie is valid.
//      If omitted or null, uses the path of the calling document.
//    [domain] - String object indicating the domain for which the cookie is
//      valid.  If omitted or null, uses the domain of the calling document.
//    [secure] - Boolean (true/false) value indicating whether cookie transmission
//      requires a secure channel (HTTPS).
//
//  The first two parameters are required.  The others, if supplied, must
//  be passed in the order listed above.  To omit an unused optional field,
//  use null as a place holder.  For example, to call SetCookie using name,
//  value and path, you would code:
//
//      SetCookie ("myCookieName", "myCookieValue", null, "/");
//
//  Note that trailing omitted parameters do not require a placeholder.
//
//  To set a secure cookie for path "/myPath", that expires after the
//  current session, you might code:
//
//      SetCookie (myCookieVar, cookieValueVar, null, "/myPath", null, true);
//
function SetCookie(name, value, expires, path, domain, secure) {
	document.cookie = name + '=' + escape(value) +
		((expires) ? '; expires=' + expires.toUTCString() : '') +
		((path) ? '; path=' + path : '') +
		((domain) ? '; domain=' + domain : '') +
		((secure) ? '; secure' : '');
}

//  Function to delete a cookie. (Sets expiration date to start of epoch)
//    name -   String object containing the cookie name
//    path -   String object containing the path of the cookie to delete.  This MUST
//             be the same as the path used to create the cookie, or null/omitted if
//             no path was specified when creating the cookie.
//    domain - String object containing the domain of the cookie to delete.  This MUST
//             be the same as the domain used to create the cookie, or null/omitted if
//             no domain was specified when creating the cookie.
//
function DeleteCookie(name, path, domain) {
	if (GetCookie(name)) {
		document.cookie = name + '=' +
			((path) ? '; path=' + path : '') +
			((domain) ? '; domain=' + domain : '') +
			'; expires=Thu, 01-Jan-70 00:00:01 GMT';
	}
}

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

/** disabled_functions.js **/
// © Copyright by Aras Corporation, 2004-2007.

var isFunctionDisabled = (function() {
	var disabledFunctions = {
		'DFMEA': {
			'Save As': true,
			'Version': true
		},
		'FileExchangePackageFile': {
			'Copy': true,
			'Paste': true,
			'Paste Special': true
		},
		'Language': {
			'Save As': true
		},
		'Process Planner': {
			'Save As': true,
			'Version': true
		},
		'Project': {
			'Save As': true
		},
		'Project Template': {
			'Save As': true
		},
		'Workflow Process': {
			'Promote': true,
			'No Tabs': true
		},
		'SavedSearch': {
			'Save As': true
		},
		'SelfServiceReport': {
			'Save As': true
		},
		'CAD': {
			'Save As': true
		},
		'Project Task': {
			'Lock': true,
			'Unlock': true
		},
		'FMEA Task': {
			'Lock': true,
			'Unlock': true
		},
		'InBasket Task': {
			'Lock': true,
			'Unlock': true,
			'Delete': true
		},
		'Express ECO EDR': {
			'New': true,
			'Delete': true,
			'Copy': true,
			'Promote': true
		},
		'cmf_ContentType': {
			'Save As': true
		},
		'xClassificationTree_ItemType': {
			'Pick Replace': true,
			'Lock': true,
			'Unlock': true,
			'Copy': true,
			'Paste': true,
			'Paste Special': true
		},
		'fr_RepType_Characteristic': {
			'Pick Replace': true
		},
		'ItemType_xPropertyDefinition': {
			'Pick Replace': true,
			'Lock': true,
			'Unlock': true
		},
		'xPropertyDefinition': {
			'Copy': true,
			'Save As': true
		},
		'xClass_xPropertyDefinition': {
			'Copy': true
		},
		'gn_GraphViewItemType': {
			'Pick Replace': true,
			'Lock': true,
			'Unlock': true
		}
	};

	function isFunctionDisabled(itemTypeName, aFunction) {
		if (disabledFunctions[itemTypeName]) {
			return disabledFunctions[itemTypeName][aFunction];
		}
		return false;
	}

	return isFunctionDisabled;
})();

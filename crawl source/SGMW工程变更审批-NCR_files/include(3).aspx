
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

/** BrowserInfo.js **/
function BrowserInfo(userAgent) {
	userAgent = userAgent || window.navigator.userAgent;

	//private properties
	var browserCode;
	var versionStr;
	//variables for private properties initialization
	var knownBrowsers = {
			'edge': {
				minCertifiedVersions: 15,
				getNameToDisplay: function() {
					return 'Microsoft Edge ' + parseInt(versionStr, 10);
				},
				minimalVersion: 15,
				patterns: [/Edge\/(\d+)/]
			},
			'ch': {
				minCertifiedVersions: 66,
				getNameToDisplay: function() {
					return 'Chrome ' + parseInt(versionStr, 10);
				},
				minimalVersion: 66,
				patterns: [/Chrome\/(\S+)/]
			},
			'ff': {
				certifiedVersions: {
					60: true
				},
				getNameToDisplay: function() {
					return 'FireFox ' + parseInt(versionStr, 10);
				},
				minimalVersion: 60,
				patterns: [/Firefox\/(\S+)/]
			},
			'ie': {
				certifiedVersions: {
					11: true
				},
				getNameToDisplay: function() {
					var declaredIEVersion = parseInt(versionStr, 10);
					//Trident/X.X appeared in userAgent string in IE 8
					//Presence of this string will help us detect IE working in compatibility mode
					var tridentVersionToIEVersion = {
						'4.0': 8,
						'5.0': 9,
						'6.0': 10,
						'7.0': 11
					};
					var res;
					var matcher = userAgent.match(/Trident\/(\S+);/);
					var tridentVersion;
					var realIEVersion;

					//default result
					res = 'Internet Explorer ' + declaredIEVersion;
					//detect for compatibility mode
					if (matcher) {
						tridentVersion = matcher[1];
						realIEVersion = tridentVersionToIEVersion[tridentVersion];
						if (realIEVersion && realIEVersion != declaredIEVersion) {
							res = 'Internet Explorer ' + realIEVersion + ' in Internet Explorer ' + declaredIEVersion + ' Compatibility View Mode';
						}
					}

					return res;
				},
				minimalVersion: 11,
				patterns: [
					//for IE 2.0 - 10.0
					/MSIE (\S+);/,
					//for IE 11.0 and perhaps for later versions
					/Trident\/.*rv:([0-9]{1,}[\.0-9]{0,})/
				]
			},
			'sa': {
				certifiedVersions: {
				},
				getNameToDisplay: function() {
					return 'Safari ' + parseInt(versionStr, 10);
				},
				minimalVersion: Number.POSITIVE_INFINITY,
				patterns: [/Version\/(\S+).* Safari\/\S+/]
			}
		};
	var patterns;
	var regExp;
	var matcher;
	var candidateCode;

	//private properties initialization
	for (candidateCode in knownBrowsers) {
		patterns = knownBrowsers[candidateCode].patterns;
		while (regExp = patterns.shift()) {//jshint ignore:line
			matcher = userAgent.match(regExp);
			if (matcher) {
				browserCode = candidateCode;
				//we need browser version with not more than two elements of version number.
				//Browser version in form "11.22" is enough for our needs.
				versionStr = (matcher[1].match(new RegExp('[^.]+(?:\.[^.]+){0,1}')))[0];//jshint ignore:line
				break;
			}
		}
		if (browserCode !== undefined) {
			break;
		}
	}

	//public methods
	this.isFf = function() {
		return browserCode === 'ff';
	};
	this.isIe = function() {
		return browserCode === 'ie';
	};
	this.isCh = function() {
		return browserCode === 'ch';
	};
	this.isEdge = function() {
		return browserCode === 'edge';
	};
	this.isKnown = function() {
		return Boolean(browserCode);
	};
	this.isSupported = function() {
		return Boolean(browserCode && parseFloat(versionStr) >= knownBrowsers[browserCode].minimalVersion);
	};
	this.isCertified = function() {
		var knownBrowser = knownBrowsers[browserCode];
		var browserVersion = parseFloat(versionStr);
		return Boolean(browserCode && (
					(knownBrowser.minCertifiedVersions && browserVersion >= knownBrowser.minCertifiedVersions) ||
					(knownBrowser.certifiedVersions && knownBrowser.certifiedVersions[browserVersion])
				));
	};
	this.getBrowserName = function() {
		var res;
		if (browserCode) {
			res = knownBrowsers[browserCode].getNameToDisplay();
		} else {
			res = '';
		}
		return res;
	};
	this.getBrowserCode = function() {
		return browserCode;
	};
	this.getMajorVersionNumber = function() {
		return parseInt(versionStr, 10);
	};
	Object.defineProperty(this, 'OSName', {
			writable: false,
			configurable: false,
			enumerable: true,
			value: (function() {
				var OSName = 'Unknown';
				if (userAgent.indexOf('Win') != -1) {
					OSName = 'Windows';
				}
				if (userAgent.indexOf('Mac') != -1) {
					OSName = 'MacOS';
				}
				return OSName;
			}())
		}
	);
}

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

/** CultureInfo\DateTimeFormatInfo.js **/
(function() {
	function BaseDateTimeFormatInfo() {
		this.defaultLocale = 'en-us';
		this.ISOPattern = /yyyy-MM-ddTHH:mm:ss(\.SSS)?/;

		Object.defineProperty(this, 'tzInfo', {
			get: function() {
				var topWnd = TopWindowHelper.getMostTopWindowWithAras(window);
				return topWnd.aras.browserHelper.tzInfo;
			}
		});

		Object.defineProperty(this, '_dateLocale', {
			get: function() {
				return dojo.require('dojo.date.locale');
			}
		});

		Object.defineProperty(this, '_dateStamp', {
			get: function() {
				return dojo.require('dojo.date.stamp');
			}
		});
	}

	var _formatCharMappingArray = [
		//http://cldr.unicode.org/translation/date-time-patterns
		{key: 'z', value: 'Z'},
		{key: 'F', value: 's'},
		{key: 'K', value: 'vz'},
		{key: 'g', value: 'G'},
		{key: 'tt', value: 'a'},
		{key: 't', value: 'a'},
		{key: 'dddd', value: 'EEEE'},
		{key: 'ddd', value: 'EEE'}
	];

	function _convertToCLDRDateFormat(pattern) {
		var index = 0;
		var mappingItem;

		for (index; index < _formatCharMappingArray.length; index += 1) {
			mappingItem = _formatCharMappingArray[index];
			pattern = pattern.replace(mappingItem.key, mappingItem.value);
		}
		return pattern;
	}
	/**
	 * @return {number}  offset between time zones
	 */
	BaseDateTimeFormatInfo.prototype.OffsetBetweenTimeZones = function(date, tzname1, tzname2) {
		tzname1 = tzname1 || 'UTC';
		tzname2 = tzname2 || 'UTC';
		return Math.round(this.tzInfo.getTimeZoneOffset(date, tzname1) - this.tzInfo.getTimeZoneOffset(date, tzname2));
	};

	BaseDateTimeFormatInfo.prototype.HasTimeZone = function(tzname) {
		if (!tzname || tzname.trim().length === 0) {
			return true;
		}
		try {
			this.tzInfo.getTimeZoneOffset(new Date(), tzname);
			return true;
		} catch (ex) {
			return false;
		}
	};

	BaseDateTimeFormatInfo.prototype.Parse = function(dateStr, datePattern, locale) {
		var isoDate = this._dateStamp.fromISOString(dateStr);
		if (isoDate) {
			return isoDate;
		}
		var options = {};

		if (datePattern) {
			var selector = this.getSelector(datePattern);
			if (selector !== null) {
				options.selector = selector;
			}
			options.datePattern = _convertToCLDRDateFormat(datePattern);
		}
		options.locale = (locale) ? locale : this.defaultLocale;
		return this._dateLocale.parse(dateStr, options);
	};

	BaseDateTimeFormatInfo.prototype.Format = function(date, datePattern, locale) {
		var options = {};
		if (datePattern) {
			options.selector = this.getSelector(datePattern);
			options.datePattern = _convertToCLDRDateFormat(datePattern);
		}
		options.locale = (locale) ? locale : this.defaultLocale;
		if (this.ISOPattern.test(datePattern)) {
			var isoStr = this.toISOString(date, {selector: ''});
			if (isoStr) {
				return isoStr;
			}
		}
		return this._dateLocale.format(date, options);
	};

	//computes selecter from datePattern (see http://dojotoolkit.org/reference-guide/dojo/date/locale/format.html#dojo-date-locale-format)
	BaseDateTimeFormatInfo.prototype.getSelector = function(datePattern) {
		var timeReg = /[hHmstfF]/;
		var dateReg = /[Mdy]/;
		var isTime = timeReg.test(datePattern);
		var isDate = dateReg.test(datePattern);
		return ((isTime && isDate) || (!isTime && !isDate)) ? 'date' : (isTime) ? 'time' : 'date';
	};

	BaseDateTimeFormatInfo.prototype.toISOString = function(dateObject, options) { //dateObject - Date, options - dojo.date.stamp.__Options?
		//	summary:
		//		Format a Date object as a string according a subset of the ISO-8601 standard
		//
		//	description:
		//		When options.selector is omitted, output follows [RFC3339](http://www.ietf.org/rfc/rfc3339.txt)
		//		The local time zone is included as an offset from GMT, except when selector=="time" (time without a date)
		//		Does not check bounds.  Only years between 100 and 9999 are supported.
		//
		//	dateObject:
		//		A Date object
		var _ = function(n) { return (n < 10) ? '0' + n : n; };
		options = options || {};
		var formattedDate = [];
		getter = 'get';
		date = '';
		if (options.selector !== 'time') {
			var year = dateObject[getter + 'FullYear']();
			date = ['0000'.substr((year + '').length) + year, _(dateObject[getter + 'Month']() + 1), _(dateObject[getter + 'Date']())].join('-');
		}
		formattedDate.push(date);
		if (options.selector !== 'date') {
			var time = [_(dateObject[getter + 'Hours']()), _(dateObject[getter + 'Minutes']()), _(dateObject[getter + 'Seconds']())].join(':');
			var millis = dateObject[getter + 'Milliseconds']();
			if (options.milliseconds) {
				time += '.' + (millis < 100 ? '0' : '') + _(millis);
			}
			formattedDate.push(time);
		}
		return formattedDate.join('T'); // String
	};

	DateTimeFormatInfo = function(locale) {
		if (!(this instanceof BaseDateTimeFormatInfo)) {
			throw 'The class DateTimeFormatInfo doesn\'t initialize!';
		}
		var localeBundle = this._dateLocale._getGregorianBundle(locale);

		this.ShortDatePattern = localeBundle['dateFormat-short'];
		this.LongDatePattern = localeBundle['dateFormat-long'];
		this.ShortTimePattern = localeBundle['timeFormat-short'];
		this.LongTimePattern = localeBundle['timeFormat-long'];
		this.FullDateTimePattern = this.LongDatePattern.concat(' ', this.LongTimePattern);
		this.UniversalSortableDateTimePattern = 'yyyy-MM-ddTHH:mm:ssZ';
	};

	DateTimeFormatInfo.initClass = function() {
		DateTimeFormatInfo.prototype = new BaseDateTimeFormatInfo();
		delete DateTimeFormatInfo.initClass;
	};

	window.DateTimeFormatInfo = DateTimeFormatInfo;
})();

/** CultureInfo\CultureInfo.js **/
function CultureInfo(locale) {
	if (!CultureInfo.initialized) {
		throw 'The class CultureInfo doesn\'t initialize!';
	}
	var _name = locale;
	var _dateFormat = null;

	Object.defineProperty(this, 'Name', {writable: false, configurable: false, enumerable: true, value: locale});
	Object.defineProperty(this, 'DateTimeFormat', {
		get: function() {
			if (!_dateFormat) {
				_dateFormat = new DateTimeFormatInfo(_name);
			}
			return _dateFormat;
		}
	});
}

CultureInfo.initClass = function() {
	delete CultureInfo.initClass;
	DateTimeFormatInfo.initClass();

	CultureInfo.CreateSpecificCulture = function(name) {
		return new CultureInfo(name);
	};

	Object.defineProperty(CultureInfo, 'initialized', {writable: false, configurable: false, enumerable: true, value: true});
	Object.defineProperty(CultureInfo, 'InvariantCulture', {writable: false, configurable: false, enumerable: true, value: new CultureInfo('en-us')});
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

/** client_cache.js **/
// © Copyright by Aras Corporation, 2004-2009.

//////////////+++++++++  CacheResponse  +++++++++//////////////////////////
function CacheResponse(success, msg, item) {
	if (success === undefined) {
		success = false;
	}
	if (msg === undefined) {
		msg = '';
	}

	this.success = success;
	this.message = msg;
	this.item = item;
}
//////////////---------  CacheResponse  ---------//////////////////////////

//////////////+++++++++  ClientCache  +++++++++//////////////////////////
function ClientCache(arasObj) {
	this.arasObj = arasObj;
	this.dom = Aras.prototype.createXMLDocument();
	this.dom.loadXML('<Innovator><Items/></Innovator>');
}

ClientCache.prototype.makeResponse = function ClientCacheMakeResponse(success, msg, item) {
	return (new CacheResponse(success, msg, item));
};

ClientCache.prototype.addItem = function ClientCacheAddItem(item) {
	if (!item) {
		return;
	}
	this.dom.selectSingleNode('/Innovator/Items').appendChild(item);
};

ClientCache.prototype.updateItem = function ClientCacheUpdateItem(item, isMergeItems) {
	var itemID = item.getAttribute('id');
	var prevItem = this.getItem(itemID);

	if (prevItem) {
		if (isMergeItems) {
			this.arasObj.mergeItem(prevItem, item);
		} else {
			prevItem.parentNode.replaceChild(item.cloneNode(true), prevItem);
		}
	} else {
		this.addItem(item);
	}
};

ClientCache.prototype.updateItemEx = function ClientCacheUpdateItemEx(oldItm, newItm) {
	var oldID = oldItm.getAttribute('id');
	var newID = newItm.getAttribute('id');

	var prevItem = this.dom.selectSingleNode('/Innovator/Items/Item[@id="' + oldID + '"]');
	if (prevItem) {
		prevItem.parentNode.replaceChild(newItm.cloneNode(true), prevItem);
	}
	if (!prevItem && (!oldItm || !oldItm.parentNode)) {
		this.addItem(newItm);
	}

	//BUGBUG: Situation when versionable item is in root of cache is not handled.
	//TODO: Remove update of cache from RefreshWindows
	if (oldItm.parentNode) {
		if (oldItm.parentNode.nodeName == 'related_id' && !this.arasObj.isTempEx(oldItm)) {
			var relNd = oldItm.parentNode.parentNode;
			var relNdBehaviour = this.arasObj.getItemProperty(relNd, 'behavior');
			if (relNdBehaviour && relNdBehaviour != 'float' && relNdBehaviour != 'hard_float') {
				var strBody = '<Item action="get" type="' + relNd.getAttribute('type') +
					'" id="' + relNd.getAttribute('id') + '" select="related_id" />';
				var res = this.arasObj.soapSend('ApplyItem', strBody);
				if (res.getFaultCode().toString() === '0') {
					var tmpItm = res.results.selectSingleNode(this.arasObj.XPathResult('/Item/related_id/Item'));
					if (tmpItm) {
						newItm = tmpItm;
					}
				}
			}
		}

		var newItmCloned = newItm.cloneNode(true);
		oldItm.parentNode.replaceChild(newItmCloned, oldItm);
	}

	var oldItms = oldItm.selectNodes('.//Item[@isTemp="1" or @isDirty="1"]');
	for (var i = 0; i < oldItms.length; i++) {
		var oldItmID = oldItms[i].getAttribute('id');
		if (oldItmID == newID) {
			continue;
		}
		var newOldItm = newItm.selectSingleNode('.//Item[@id="' + oldItmID + '"]');

		//both updateItem and deleteItem affect only root level of cache.
		if (newOldItm) {
			this.updateItem(newOldItm);
		} else {
			this.deleteItem(oldItmID);
		}
	}

	//update configurations in cache
	if (oldID == newID) {//to not touch behaviours of corresponding properties
		var nodesInsideConfigurations = this.dom.selectNodes('/Innovator/Items/Item/*//Item[ancestor::*[local-name()!="related_id"] and @id="' + oldID + '"]');
		for (i = 0, L = nodesInsideConfigurations.length; i < L; i++) {
			var nd = nodesInsideConfigurations[i];
			nd.parentNode.replaceChild(newItm.cloneNode(true), nd);
		}
	}
};

ClientCache.prototype.deleteItem = function ClientCacheDeleteItem(itemID) {
	var prevItem = this.getItem(itemID);
	if (prevItem) {
		return prevItem.parentNode.removeChild(prevItem);
	}

	return null;
};

ClientCache.prototype.deleteItems = function ClientCacheDeleteItems(xpath) {
	var nodes = this.getItemsByXPath(xpath);
	for (var i = 0; i < nodes.length; i++) {
		var parentNode = nodes[i].parentNode;
		if (parentNode) {
			parentNode.removeChild(nodes[i]);
		}
	}
};

ClientCache.prototype.getItem = function ClientCacheGetItem(itemID) {
	var item = this.dom.selectSingleNode('/Innovator/Items/Item[@id="' + itemID + '"]');
	return item;
};

ClientCache.prototype.getItemByXPath = function ClientCacheGetItemByXPath(xpath) {
	return this.dom.selectSingleNode(xpath);
};

ClientCache.prototype.getItemsByXPath = function ClientCacheGetItemsByXPath(xpath) {
	return this.dom.selectNodes(xpath);
};

ClientCache.prototype.hasItem = function ClientCacheHasItem(itemID) {
	return (this.getItem(itemID) !== null);
};
//////////////---------  ClientCache  ---------//////////////////////////

/** qry_object.js **/
// © Copyright by Aras Corporation, 2004-2007.

function QryItem(arasObj, itemTypeName) {
	this.arasObj = arasObj;
	this.dom = arasObj.createXMLDocument();
	if (itemTypeName) {
		this.itemTypeName = itemTypeName;
	}

	this.initQry(this.itemTypeName);
}

QryItem.prototype.dom = null;
QryItem.prototype.item = null;
QryItem.prototype.itemTypeName = '';
QryItem.prototype.response = null;
QryItem.prototype.result = null;

/*
*/
QryItem.prototype.initQry = function QryItemInitQry(itemTypeName, preservePrevResults) {
	if (preservePrevResults === undefined) {
		preservePrevResults = false;
	}

	this.itemTypeName = itemTypeName;
	this.dom.loadXML('<Item type="' + this.itemTypeName + '" action="get" />');
	this.item = this.dom.documentElement;

	if (!preservePrevResults) {
		var topWnd = this.arasObj.getMostTopWindowWithAras(window);
		this.response = new topWnd.SOAPResults(this.arasObj, SoapConstants.EnvelopeBodyStart + '<Result />' + SoapConstants.EnvelopeBodyEnd);
		this.result = this.response.getResult();
	}
};

QryItem.prototype.setItemType = function QryItemSetItemType(itemTypeName) {
	if (this.itemTypeName == itemTypeName) {
		return;
	}
	this.initQry(itemTypeName, false);
};

/*
*/
QryItem.prototype.setCriteria = function QryItemSetCriteria(propertyName, value, condition) {
	if (condition === undefined) {
		condition = 'eq';
	}

	var criteria = this.item.selectSingleNode(propertyName);
	if (!criteria) {
		criteria = this.dom.createElement(propertyName);
		this.item.appendChild(criteria);
	}

	criteria.text = value;
	criteria.setAttribute('condition', condition);
};

QryItem.prototype.setCriteriaForMlString = function QryItemSetCriteriaForMlString(criteriaNode, condition) {
	if (condition === undefined) {
		condition = 'eq';
	}
	if (!criteriaNode) {
		return;
	}

	var propertyName = criteriaNode.nodeName;
	var prefix = criteriaNode.prefix;
	var value = criteriaNode.text;
	var language = criteriaNode.getAttribute('xml:lang');
	var xpath = propertyName;

	if (prefix == 'i18n') {
		xpath = '//*[local-name() = \'' + propertyName + '\' and namespace-uri()=\'' + this.arasObj.translationXMLNsURI + '\' and @xml:lang=\'' + language + '\']';
	}

	var criteriaNd = this.item.selectSingleNode(xpath);
	if (!criteriaNd) {
		criteriaNd = this.dom.documentElement.appendChild(criteriaNode.cloneNode(false));
	}

	criteriaNd.text = value;
	criteriaNd.setAttribute('condition', condition);
};

QryItem.prototype.setPropertyCriteria = function QryItemSetPropertyCriteria(propertyName, critName, value, condition, typeOfItem) {
	if (condition === undefined) {
		condition = 'eq';
	}

	var criteria = this.item.selectSingleNode(propertyName);
	if (!criteria) {
		criteria = this.dom.createElement(propertyName);
		this.item.appendChild(criteria);
	}

	var itm = criteria.selectSingleNode('Item');
	if (!itm) {
		itm = this.dom.createElement('Item');
		criteria.text = '';
		criteria.appendChild(itm);
	}
	if (typeOfItem) {
		itm.setAttribute('type', typeOfItem);
	}
	itm.setAttribute('action', 'get');

	criteria = itm.selectSingleNode(critName);
	if (!criteria) {
		criteria = this.dom.createElement(critName);
		itm.appendChild(criteria);
	}

	criteria.text = value;
	criteria.setAttribute('condition', condition);
};

QryItem.prototype.setRelationshipCriteria = function QryItemSetRelationshipCriteria(relType, propertyName, value, condition) {
	if (condition === undefined) {
		condition = 'eq';
	}

	var rels = this.item.selectSingleNode('Relationships');
	if (!rels) {
		rels = this.dom.createElement('Relationships');
		this.item.appendChild(rels);
	}

	var itm = rels.selectSingleNode('Item[@type="' + relType + '"]');
	if (!itm) {
		itm = this.dom.createElement('Item');
		rels.appendChild(itm);
		itm.setAttribute('type', relType);
		itm.setAttribute('action', 'get');
	}

	var criteria = itm.selectSingleNode(propertyName);
	if (!criteria) {
		criteria = this.dom.createElement(propertyName);
		itm.appendChild(criteria);
	}

	criteria.text = value;
	criteria.setAttribute('condition', condition);
};

QryItem.prototype.setRelationshipPropertyCriteria = function QryItemSetRelationshipPropertyCriteria(relType, propertyName, critName, value, condition) {
	if (condition === undefined) {
		condition = 'eq';
	}

	var rels = this.item.selectSingleNode('Relationships');
	if (!rels) {
		rels = this.dom.createElement('Relationships');
		this.item.appendChild(rels);
	}

	var itm = rels.selectSingleNode('Item[@type="' + relType + '"]');
	if (!itm) {
		itm = this.dom.createElement('Item');
		rels.appendChild(itm);
		itm.setAttribute('type', relType);
		itm.setAttribute('action', 'get');
	}

	var tmpCrit = itm.selectSingleNode(propertyName);
	if (!tmpCrit) {
		tmpCrit = this.dom.createElement(propertyName);
		itm.appendChild(tmpCrit);
	}

	itm = tmpCrit.selectSingleNode('Item');
	if (!itm) {
		itm = this.dom.createElement('Item');
		tmpCrit.appendChild(itm);
	}

	var criteria = itm.selectSingleNode(critName);
	if (!criteria) {
		criteria = this.dom.createElement(critName);
		itm.appendChild(criteria);
	}

	criteria.text = value;
	criteria.setAttribute('condition', condition);
};

QryItem.prototype.getCriteriesString = function() {
	return !this.item.childNodes.length ? '' : Array.prototype.map.call(this.item.childNodes, function(el) {
		return el.xml ? el.xml.trim() : '';
	}).sort().join('');
};

QryItem.prototype.setRelationshipSearchOnly = function(relType) {
	var itm = this.item.selectSingleNode('Relationships/Item[@type="' + relType + '"]');
	if (itm) {
		itm.setAttribute('search_only', 'yes');
	}
};

QryItem.prototype.setOrderBy = function(orderBy) {
	this.item.setAttribute('order_by', orderBy);
};

QryItem.prototype.setMaxGeneration = function(maxGeneration) {
	var flag = (maxGeneration) ? '1' : '0';
	this.item.setAttribute('max_generation', flag);
};

QryItem.prototype.setLevels = function(levels) {
	this.item.setAttribute('levels', levels);
};

QryItem.prototype.getSelect = function() {
	return this.item.getAttribute('select');
};

QryItem.prototype.setSelect = function(select) {
	this.item.setAttribute('select', select);
};

QryItem.prototype.setConfigPath = function(configPath) {
	this.item.setAttribute('config_path', configPath);
};

QryItem.prototype.setPage = function(page) {
	this.item.setAttribute('page', page);
};

QryItem.prototype.getPage = function(page) {
	page = this.item.getAttribute('page');
	if (page === null) {
		page = '';
	}
	return page;
};

QryItem.prototype.getPageSize = function() {
	var pagesize = this.item.getAttribute('pagesize');
	if (!pagesize) {
		pagesize = '-1';
	}
	return pagesize;
};

QryItem.prototype.setPageSize = function(pageSize) {
	this.item.setAttribute('pagesize', pageSize);
};

QryItem.prototype.getMaxRecords = function() {
	var maxRecords = this.item.getAttribute('maxRecords');
	if (!maxRecords) {
		maxRecords = '-1';
	}
	return maxRecords;
};

QryItem.prototype.setMaxRecords = function(maxRecords) {
	this.item.setAttribute('maxRecords', maxRecords);
};

QryItem.prototype.setReturnMode = function(returnMode) {
	this.item.setAttribute('returnMode', returnMode);
};

QryItem.prototype.setItemID = function(id) {
	this.item.setAttribute('id', id);
};

QryItem.prototype.setType = function(itemTypeName) {
	this.item.setAttribute('type', itemTypeName);
};

QryItem.prototype.getType = function() {
	return this.item.getAttribute('type');
};

QryItem.prototype.getResponse = function() {
	return this.response;
};

QryItem.prototype.getResponseDOM = function() {
	return this.response.results;
};

QryItem.prototype.getResult = function() {
	return this.result;
};

QryItem.prototype.getResultDOM = function() {
	return this.result.ownerDocument;
};

QryItem.prototype.removeCriteria = function QryItemRemoveCriteria(propertyName, languageCode) {
	if (!propertyName) {
		return;
	}

	var xpath = propertyName;
	if (languageCode) {
		xpath = '*[local-name()=\'' + propertyName + '\' and namespace-uri()=\'' + this.arasObj.translationXMLNsURI + '\' and @xml:lang=\'' + languageCode + '\']';
	} else {
		xpath = propertyName;
	}

	var criteria = this.item.selectSingleNode(xpath);
	if (criteria) {
		criteria.parentNode.removeChild(criteria);
	}
};

QryItem.prototype.removePropertyCriteria = function QryItemRemovePropertyCriteria(propertyName, critName) {
	var criteria = this.item.selectSingleNode(propertyName + '/Item/' + critName);
	var itm;
	if (criteria) {
		itm = criteria.parentNode;
		itm.removeChild(criteria);
		if (!itm.selectSingleNode('.//*[.!="Relationships"]')) {
			this.removeCriteria(propertyName);
		}
	} else {
		itm = this.item.selectSingleNode(propertyName + '/Item');
		if (!itm || !itm.selectSingleNode('.//*[.!="Relationships"]')) {
			this.removeCriteria(propertyName);
		}
	}
};

QryItem.prototype.removeRelationshipCriteria = function QryItemRemoveRelationshipCriteria(relType, propertyName) {
	var criteria = this.item.selectSingleNode('./Relationships/Item[@type="' + relType + '"]/' + propertyName);
	if (criteria) {
		var itm = criteria.parentNode;
		itm.removeChild(criteria);
		if (!itm.selectSingleNode('.//*[.!="Relationships"]')) {
			itm.parentNode.removeChild(itm);
		}
	}
};

QryItem.prototype.removeRelationshipPropertyCriteria = function QryItemRemoveRelationshipPropertyCriteria(relType, propertyName, critName) {
	var criteria = this.item.selectSingleNode('./Relationships/Item[@type="' + relType + '"]/' + propertyName + '/Item/' + critName);
	var itm;
	if (criteria) {
		itm = criteria.parentNode;
		itm.removeChild(criteria);
		if (!itm.selectSingleNode('.//*[.!="Relationships"]')) {
			var parentCrit = itm.parentNode;
			parentCrit.removeChild(itm);
			this.removeRelationshipCriteria(propertyName);
		}
	} else {
		itm = this.item.selectSingleNode('./Relationships/Item[@type="' + relType + '"]/' + propertyName + '/Item');
		if (!itm || !itm.selectSingleNode('.//*[.!="Relationships"]')) {
			this.removeRelationshipCriteria(relType, propertyName);
		}
	}
};

QryItem.prototype.loadXML = function QryItemLoadXml(xmlToLoad) {
	this.dom.loadXML(xmlToLoad);
	this.item = this.dom.documentElement;
};

QryItem.prototype.removeAllCriterias = function QryItemRemoveAllCriterias() {
	this.dom.replaceChild(this.item.cloneNode(false), this.dom.documentElement);
	this.item = this.dom.documentElement;
};

QryItem.prototype.execute = function QryItemExecute(savePrevResults, soapController) {
	if (savePrevResults === undefined) {
		savePrevResults = (this.arasObj.getPreferenceItemProperty('Core_GlobalLayout', null, 'core_append_items') == 'true');
	}
	this.savePrevResults = savePrevResults;

	var res = this.arasObj.soapSend('ApplyItem', this.dom.xml, undefined, undefined, soapController);
	if (soapController) {
		return;
	}

	this.setResponse(res);

	return this.result;
};

QryItem.prototype.setResponse = function QryItemSetResponse(res) {
	if (res.getFaultCode().toString() !== '0') {
		this.arasObj.AlertError(res);
		this.result = undefined;
		return;
	}

	this.response = res;

	if (this.savePrevResults) {
		res = res.getResult();
		var fromServer = res.selectNodes('Item');
		for (var i = 0; i < fromServer.length; i++) {
			var oldItm = this.result.selectSingleNode('Item[@id="' + fromServer[i].getAttribute('id') + '"]');
			if (oldItm) {
				oldItm.parentNode.replaceChild(fromServer[i].cloneNode(true), oldItm);
			} else {
				this.result.appendChild(fromServer[i].cloneNode(true));
			}
		}
	} else {
		this.result = res.getResult();
	}
};

QryItem.prototype.syncWithClient = function QryItemSyncWithClient() {
	var res = this.getResult();
	var i;
	var prevResults = res.selectNodes('Item[@isTemp="1" or @isDirty="1"]');
	for (i = 0; i < prevResults.length; i++) {
		res.removeChild(prevResults[i]);
	}

	var clientItems = this.arasObj.itemsCache.getItemsByXPath('/Innovator/Items/Item[@type="' + this.itemTypeName + '"]');

	for (i = 0; i < clientItems.length; i++) {
		var clientItem = clientItems[i];
		var isTempOrDirty = ((clientItem.getAttribute('isTemp') == '1') || (clientItem.getAttribute('isDirty') == '1'));

		var fromServer = res.selectSingleNode('Item[@id="' + clientItem.getAttribute('id') + '"]');

		if (isTempOrDirty) {
			if (fromServer) {
				res.replaceChild(clientItem.cloneNode(true), fromServer);
			} else {
				res.appendChild(clientItem.cloneNode(true));
			}
		} else {
			//item from client cache do not contain unsaved modifications.
			//to resolve IR-002881: Erroneous caching of the lifecycle state
			if (fromServer) {
				//if item in client cache is not locked or item from server is unlocked or locked by someone else then remove item from client cache.
				var doRemoveClientItem = (!this.arasObj.isLockedByUser(clientItem)) || (!this.arasObj.isLockedByUser(fromServer));
				if (doRemoveClientItem) {
					clientItem.parentNode.removeChild(clientItem);
				}
			}
		}
	}
};

QryItem.prototype.setConditionEverywhere = function(condition) {
	var conditionTags = this.item.selectNodes('//*[@condition!=\'' + condition + '\']');
	for (var i = 0; i < conditionTags.length; i++) {
		conditionTags.item(i).setAttribute('condition', condition);
	}
};

QryItem.prototype.replaceConditionEverywhere = function(condition1, condition2) {
	var conditionTags = this.item.selectNodes('//*[@condition=\'' + condition1 + '\']');
	for (var i = 0; i < conditionTags.length; i++) {
		conditionTags.item(i).setAttribute('condition', condition2);
	}
};

QryItem.prototype.getBlock = function(blockName) {
	return this.dom.documentElement.selectSingleNode(blockName);
};

QryItem.prototype.createConditionBlock = function(blockName) {
	var b = this.dom.createElement(blockName);
	this.item.appendChild(b);
	return b;
};

QryItem.prototype.setPropertyCriteriaInBlock = function QryItemSetPropertyCriteriaInBlock(block, propertyName, critName, value, condition) {
	if (condition === undefined) {
		condition = 'eq';
	}

	if (block) {
		var criteria = block.selectSingleNode(propertyName + '/Item/' + critName + '[. = \'' + value + '\']');
		if (criteria) {
			return;
		} else {
			criteria = this.dom.createElement(propertyName);
			block.appendChild(criteria);
		}

		var itm = criteria.selectSingleNode('Item');
		if (!itm) {
			itm = this.dom.createElement('Item');
			criteria.text = '';
			criteria.appendChild(itm);
		}

		criteria = itm.selectSingleNode(critName);
		if (!criteria) {
			criteria = this.dom.createElement(critName);
			itm.appendChild(criteria);
		}

		criteria.text = value;
		criteria.setAttribute('condition', condition);
	}
};

QryItem.prototype.removePropertyCriteriaFromBlock = function QryItemRemovePropertyCriteriaFromBlock(block, propertyName, critName) {
	if (!block) {
		return;
	}

	var criterias = block.selectNodes(propertyName);
	for (var i = 0; i < criterias.length; i++) {
		criterias[i].parentNode.removeChild(criterias[i]);
	}
};

QryItem.prototype.addCondition2Block = function(block, propertyName, value, condition) {
	if (condition === undefined) {
		condition = 'eq';
	}

	if (!block || !propertyName) {
		return;
	}

	var criteria = block.selectSingleNode('*[local-name()=\'' + propertyName + '\' and . = \'' + value + '\']');
	if (criteria) {
		return;
	} else {
		criteria = this.dom.createElement(propertyName);
		block.appendChild(criteria);
	}

	criteria.text = value;
	criteria.setAttribute('condition', condition);
};

QryItem.prototype.removeCriteriaFromBlock = function(block, propertyName, languageCode) {
	if (!block || !propertyName) {
		return;
	}

	var xpath = propertyName;
	if (languageCode) {
		xpath = '*[local-name()=\'' + propertyName + '\' and namespace-uri()=\'' + this.arasObj.translationXMLNsURI + '\' and @xml:lang=\'' + languageCode + '\']';
	}

	var criterias = block.selectNodes(xpath);
	for (var i = 0; i < criterias.length; i++) {
		criterias[i].parentNode.removeChild(criterias[i]);
	}
};

QryItem.prototype.setItemAttribute = function QryItemSetItemAttribute(name, value) {
	this.item.setAttribute(name, value);
};

QryItem.prototype.removeItemAttribute = function QryItemRemoveItemAttribute(name) {
	this.item.removeAttribute(name);
};

/** clipboard.js **/
// © Copyright by Aras Corporation, 2004-2007.

/*----------------------------------------
 * FileName: clipboard.js
 *
 *
 */

function Clipboard(arasObj) {
	this.aras = arasObj;
	this.clItems = [];

	/*
	  clipboardItem.source_id = sourceID;
	  clipboardItem.source_itemtype = sourceType;
	  clipboardItem.source_keyedname = sourceKeyedName;
	  clipboardItem.relationship_id = relationshipID;
	  clipboardItem.relationship_itemtype = relationshipType;
	  clipboardItem.related_id = relatedID;
	  clipboardItem.related_itemtype = relatedType;
	  clipboardItem.related_keyedname = relatedKeyedName;
	*/

	/*
	  clipboardItem.groupIndex - defines the index of group of copied items
	*/

	this.lastCopyIndex = 0;
}

Clipboard.prototype.copy = function Clipboard_Copy(itemArr) {
	if (itemArr.length <= 0) {
		return;
	}
	this.lastCopyIndex++;
	for (var i = 0; i < itemArr.length; i++) {
		var item = itemArr[i];
		item.groupIndex = this.lastCopyIndex;
		this.clItems.push(item);
	}
};

Clipboard.prototype.paste = function Clipboard_Paste() {
	var itemArr = [];
	for (var i = 0; i < this.clItems.length; i++) {
		if (this.clItems[i].groupIndex == this.lastCopyIndex) {
			itemArr.push(this.clItems[i]);
		}
	}
	return itemArr;
};

Clipboard.prototype.getLastCopyIndex = function Clipboard_GetLastCopyIndex() {
	return this.lastCopyIndex;
};

Clipboard.prototype.isEmpty = function Clipboard_IsEmpty() {
	return this.clItems.length === 0;
};

Clipboard.prototype.getLastCopyCount = function Clipboard_GetLastCopyCount() {
	var copyCount = 0;
	for (var i = 0; i < this.clItems.length; i++) {
		if (this.clItems[i].groupIndex == this.lastCopyIndex) {
			copyCount++;
		}
	}
	return copyCount;
};

Clipboard.prototype.getLastCopyRelatedItemTypeName = function Clipboard_GetLastCopyRelatedItemTypeName() {
	if (this.isEmpty()) {
		return '';
	}
	return this.clItems[this.clItems.length - 1].related_itemtype;
};

Clipboard.prototype.getLastCopyRTName = function Clipboard_GetLastCopyRTName() {
	if (this.isEmpty()) {
		return '';
	}
	return this.clItems[this.clItems.length - 1].relationship_itemtype;
};

Clipboard.prototype.getLastCopyItem = function Clipboard_GetLastCopyItem() {
	if (this.isEmpty()) {
		return '';
	}
	return this.clItems[this.clItems.length - 1];
};

Clipboard.prototype.clear = function Clipboard_Clear() {
	this.clItems = [];
	this.lastCopyIndex = 0;
};

Clipboard.prototype.removeItem = function Clipboard_RemoveItem(index) {
	index = parseInt(index);
	if (index >= this.clItems.length) {
		return;
	}
	var needUpdateLastIndex = (this.clItems[index].groupIndex == this.lastCopyIndex);
	var i;
	for (i = index; i < this.clItems.length - 1; i++) {
		this.clItems[i] = this.clItems[i + 1];
	}
	this.clItems.pop();

	if (needUpdateLastIndex) {
		this.lastCopyIndex = 0;
		for (i = 0; i < this.clItems.length; i++) {
			if (this.clItems[i].groupIndex > this.lastCopyIndex) {
				this.lastCopyIndex = this.clItems[i].groupIndex;
			}
		}
	}
};

Clipboard.prototype.getItem = function Clipboard_GetItem(relId) {
	for (var i = 0; i < this.clItems.length; i++) {
		if (this.clItems[i].relationship_id == relId) {
			return this.clItems[i];
		}
	}
	return null;
};

/** ..\Modules\aras.innovator.AuthenticationFramework\Scripts\OAuthServerDiscovery.js **/
(function(global) {
	const discoveryPath = 'OAuthServerDiscovery.aspx';
	const configurationPath = '.well-known/openid-configuration';

	const discoveryErrorMessage = 'Cannot access OAuth Server due to incorrect Discovery configuration';
	const httpErrorMessage = 'Cannot access OAuth Server due to {0} ({1})';
	const corsErrorMessage = 'Cannot access OAuth Server due to CORS policies';

	const lastAccessibleOAuthServerUrlKey = 'lastAccessibleOAuthServerUrl';

	global.OAuthServerDiscovery = {
		discover: function(baseServerUrl) {
			const self = this;
			return this._getOAuthServerUrls(baseServerUrl)
				.then(function(oauthServerUrls) {
					// Optimization by host
					const priorityHost = self._getHost(baseServerUrl);
					oauthServerUrls = self._prioritizeHost(oauthServerUrls, priorityHost);

					// Optimization by last accessible url
					const storage = self._getStorage();
					const priorityUrl = storage.getItem(lastAccessibleOAuthServerUrlKey);
					if (priorityUrl) {
						oauthServerUrls = self._prioritizeUrl(oauthServerUrls, priorityUrl);
					}

					const errorInfos = [];
					let promise = oauthServerUrls.reduce(function(promise, oauthServerUrl) {
						return promise.catch(function() {
							return self._getConfiguration(oauthServerUrl)
								.then(function(configuration) {
									storage.setItem(lastAccessibleOAuthServerUrlKey, oauthServerUrl);
									return configuration;
								})
								.catch(function(error) {
									errorInfos.push({
										error: error,
										url: oauthServerUrl
									});
									return Promise.reject(error);
								});
						});
					}, Promise.reject());
					promise = promise.catch(function(lastError) {
						return Promise.reject(
							oauthServerUrls.length == 1 ?
								lastError :
								self._combineErrorInfos(errorInfos));
					});
					return promise;
				});
		},

		_getOAuthServerUrls: function(baseServerUrl) {
			const discoveryUrl = baseServerUrl + discoveryPath;

			return fetch(discoveryUrl, {method: 'GET', credentials: 'same-origin'})
				.then(function(response) {
					return response.json();
				})
				.then(function(discoveryJson) {
					if (!discoveryJson || !Array.isArray(discoveryJson.locations) || !discoveryJson.locations.length) {
						return Promise.reject(new Error(discoveryErrorMessage));
					}

					const oauthServerUrls = discoveryJson.locations.map(function(location) {
						return location.uri;
					});
					return oauthServerUrls;
				});
		},

		_getConfigurationEndpoint: function(oauthServerUrl) {
			oauthServerUrl = oauthServerUrl.endsWith('/') ? oauthServerUrl : (oauthServerUrl + '/');
			const configurationEndpoint = oauthServerUrl + configurationPath;
			return configurationEndpoint;
		},

		_getConfiguration: function(oauthServerUrl) {
			const configurationEndpoint = this._getConfigurationEndpoint(oauthServerUrl);
			return fetch(configurationEndpoint, {method: 'GET', credentials: 'include'})
				.then(function(response) {
					if (response.status !== 200) {
						const errorMessage = httpErrorMessage
							.replace('{0}', response.status)
							.replace('{1}', response.statusText);
						return Promise.reject(new Error(errorMessage));
					}

					return response.json();
				})
				.catch(function(error) {
					const polyfillCorsErrorMessage = 'Network request failed';
					const firefoxCorsErrorMessage = 'NetworkError when attempting to fetch resource.';
					const defaultCorsErrorMessage = 'Failed to fetch'; // Chrome, Edge

					const isCorsError = (
						error && error.message &&
						error.message === polyfillCorsErrorMessage ||
						error.message === firefoxCorsErrorMessage ||
						error.message === defaultCorsErrorMessage
					);

					if (isCorsError) {
						return Promise.reject(new Error(corsErrorMessage));
					}

					return Promise.reject(error);
				});
		},

		_combineErrorInfos: function(errorInfos) {
			return errorInfos.reduce(function(message, errorInfo) {
				const errorMessage = errorInfo.error;
				const url = errorInfo.url;
				if (message.length) {
					message = message + '\n\n';
				}
				return message +
					errorMessage + '\n' +
					'  from ' + url;
			}, '');
		},

		_getHost: function(url) {
			const location = document.createElement('a');
			location.href = url;
			return location.hostname.toLowerCase();
		},

		_prioritizeHost: function(oauthServerUrls, priorityHost) {
			const self = this;
			const urlsWithPriorityHost = [];
			const urlsWithoutPriorityHost = [];
			oauthServerUrls.forEach(function(oauthServerUrl) {
				const host = self._getHost(oauthServerUrl);
				if (host === priorityHost) {
					urlsWithPriorityHost.push(oauthServerUrl);
				} else {
					urlsWithoutPriorityHost.push(oauthServerUrl);
				}
			});
			return urlsWithPriorityHost.concat(urlsWithoutPriorityHost);
		},

		_prioritizeUrl: function(oauthServerUrls, priorityUrl) {
			priorityUrl = priorityUrl.toLowerCase();
			const urlsWithPriorityUrl = [];
			const urlsWithoutPriorityUrl = [];
			oauthServerUrls.forEach(function(oauthServerUrl) {
				if (oauthServerUrl.toLowerCase() === priorityUrl) {
					urlsWithPriorityUrl.push(oauthServerUrl);
				} else {
					urlsWithoutPriorityUrl.push(oauthServerUrl);
				}
			});
			return urlsWithPriorityUrl.concat(urlsWithoutPriorityUrl);
		},

		_getStorage: function() {
			return localStorage;
		}
	};
})(window);

/** ..\Modules\aras.innovator.AuthenticationFramework\Scripts\OAuthClient.ImplicitGrant.js **/
(function(global) {
	const defaultProtocolInfo = {
		authorization_header: 'Authorization',
		www_authenticate_header: 'WWW-Authenticate',
		unauthorized_status_code: 401
	};
	let protocolInfo;

	const oidcSettings = {
		authority: '',

		client_id: '',

		redirect_uri: '',
		popup_redirect_uri: '',
		silent_redirect_uri: '',

		post_logout_redirect_uri: '',

		response_type: 'id_token token',

		scope: 'openid Innovator',

		accessTokenExpiringNotificationTime: 5 * 60, // 5 min
		automaticSilentRenew: true,

		loadUserInfo: false,

		popupWindowFeatures: 'location=no,toolbar=no,width=950,height=550,left=200,top=150;' // TODO: Implement resize on load in OAuthServer/login page
	};

	let oidc;
	let oidcUserManager;
	let oidcUser;

	global.OAuthClient = {
		init: function(oauthClientId, baseClientUrl, oauthServerConfiguration) {
			const self = this;
			oidc = null;
			oidcUserManager = null;
			oidcUser = null;
			const authorizeEndpoint = oauthServerConfiguration.authorization_endpoint;
			const authority = authorizeEndpoint.replace(/connect\/authorize$/i, '');
			protocolInfo = Object.assign({}, defaultProtocolInfo, oauthServerConfiguration.protocol_info);
			return new Promise(function(resolve, reject) {
				require(['Vendors/oidc-client.min'], function(Oidc) {
					try {
						oidc = Oidc;
						// oidc.Log.logger = console;
						// oidc.Log.level = oidc.Log.DEBUG;
						oidcSettings.authority = authority;
						oidcSettings.metadata = oauthServerConfiguration; // To avoid extra request for metadata by openid-client library
						oidcSettings.client_id = oauthClientId;
						oidcSettings.redirect_uri = baseClientUrl + 'OAuth/RedirectCallback';
						oidcSettings.popup_redirect_uri = baseClientUrl +  'OAuth/PopupCallback';
						oidcSettings.silent_redirect_uri = baseClientUrl + 'OAuth/SilentCallback';
						oidcSettings.post_logout_redirect_uri = baseClientUrl + 'OAuth/PostLogoutCallback';
						const storage = new oidc.WebStorageStateStore({
							store: new oidc.InMemoryWebStorage()
						});
						oidcSettings.userStore = storage;
						oidcUserManager = new oidc.UserManager(oidcSettings);
						oidcUserManager.events.addUserLoaded(self._onUserLoaded);
						oidcUserManager.events.addUserUnloaded(self._onUserUnloaded);
						oidcUserManager.events.addUserSignedOut(self._onUserSignedOut);
						resolve();
					}
					catch (e) {
						reject(e);
					}
				});
			});
		},

		login: function(options) {
			options = this._convertOptionsToOidcSettings(options);
			let silentPromise;
			if (options.prompt === 'login' ||
				options.prompt === 'select_account' ||
				!this._isSilentRenewActive()) {
				silentPromise = Promise.reject();
			} else {
				// Try update session with silent login.
				// Additonally it's needed to initialize `oidcUser`.
				silentPromise = oidcUserManager.signinSilent();
			}
			return silentPromise
				.then(function(user) {
					oidcUser = user;
					return {
						status: 'logged-in'
					};
				})
				.catch(function() {
					// There are no active sessions so signin
					return oidcUserManager.signinRedirect(options)
						.then(function() {
							return {
								status: 'in-progress'
							};
						});
				});
		},

		relogin: function(options) {
			const self = this;
			options = this._convertOptionsToOidcSettings(options);
			let silentPromise;
			if (options.prompt === 'login' ||
				options.prompt === 'select_account' ||
				!this._isSilentRenewActive()) {
				silentPromise = Promise.reject();
			} else {
				// Try update session with silent login.
				silentPromise = oidcUserManager.signinSilent();
			}
			return silentPromise
				.catch(function() {
					if (self.popupPromise) {
						return self.popupPromise;
					}
					self.popupPromise = oidcUserManager.signinPopup(options)
						.then(function(user) {
							self.popupPromise = null;
							return user;
						}, function(err) {
							self.popupPromise = null;
							return Promise.reject(err);
						});
					return self.popupPromise;
				})
				.then(function(user) {
					oidcUser = user;
				});
		},

		logout: function() {
			return oidcUserManager.clearStaleState()
				.catch(this._catchError) // Continue signout in any case
				.then(function() {
					return oidcUserManager.signoutRedirect()
						.then(function() {
							oidcUser = null;
						});
				});
		},

		isLogged: function() {
			return !!oidcUser;
		},

		getToken: function() {
			this._ensureUserLoggedIn();
			return oidcUser.access_token;
		},

		get unauthorizedStatusCode() {
			return protocolInfo.unauthorized_status_code;
		},

		get authorizationHeaderName() {
			return protocolInfo.authorization_header;
		},

		getAuthorizationHeader: function() {
			const headerObject = {};
			const headerName = this.authorizationHeaderName;
			if (headerName && oidcUser) {
				headerObject[headerName] = this._getTokenType() + ' ' + this.getToken();
			}

			return headerObject;
		},

		_convertOptionsToOidcSettings: function(options) {
			const oidcOptions = {
				extraQueryParams: {}
			};
			options = options || {};
			this._assignProperty('prompt', options, oidcOptions);
			this._assignProperty('login_hint', options, oidcOptions);
			this._assignProperty('database', options, oidcOptions.extraQueryParams);
			this._assignProperty('authentication_type', options, oidcOptions.extraQueryParams);
			this._assignProperty('state', options, oidcOptions);
			return oidcOptions;
		},

		_assignProperty: function(propertyName, fromObject, toObject) {
			if (fromObject[propertyName]) {
				toObject[propertyName] = fromObject[propertyName];
			}
		},

		_catchError: function(e) {
			oidc.Log.error('Unhandled error: ' + e);
		},

		_ensureUserLoggedIn: function() {
			if (!this.isLogged()) {
				throw new Error('You are not logged in!');
			}
		},

		_getTokenType: function() {
			this._ensureUserLoggedIn();
			return oidcUser.token_type;
		},

		_onUserLoaded: function(loadedUser) {
			oidcUserManager.startSilentRenew();
			oidcUser = loadedUser;
		},

		_onUserUnloaded: function() {
			oidcUserManager.stopSilentRenew();
		},

		_onUserSignedOut: function() {
			// Stop silent renew when user logged out
			// because it may login again under another user
			// and during silent renew we may load access token for another user
			// but current UI still is for the initial user.
			oidcUserManager.stopSilentRenew();
		},

		_isSilentRenewActive: function() {
			return !!oidcUserManager._silentRenewService._callback;
		}
	};
})(window);

/** ..\Modules\aras\user.js **/
(function(ArasCore) {
	const getAras = function() {
		return window.aras;
	};

	const xmlModule = ArasModules.xml;
	const storage = {};
	const faultToJSON = ArasModules.aml.faultToJSON;
	const passwordExpiredConst =
		'SOAP-ENV:Server.Authentication.PasswordIsExpired';

	function showDialog(type, addinArgs) {
		const arasObj = getAras();
		const data = {
			aras: arasObj,
			dialogWidth: 300,
			dialogHeight: 180,
			center: true,
			content: 'changeMD5Dialog.html'
		};

		Object.assign(data, addinArgs);

		if (type === 'passwordExpired') {
			Object.assign(data, {
				title: arasObj.getResource('', 'common.pwd_expired'),
				oldMsg: arasObj.getResource('', 'common.old_pwd'),
				newMsg1: arasObj.getResource('', 'common.new_pwd'),
				newMsg2: arasObj.getResource('', 'common.confirm_pwd'),
				errMsg1: arasObj.getResource('', 'common.old_pwd_wrong'),
				errMsg2: arasObj.getResource('', 'common.check_pwd_confirmation'),
				errMsg3: arasObj.getResource('', 'common.pwd_empty'),
				check_empty: true
			});
		}

		return ArasModules.Dialog.show('iframe', data).promise;
	}

	function getPasswordPolicies(msgValue) {
		const xml = xmlModule.parseString('<res>' + msgValue + '</res>');
		const obj = ArasModules.xmlToJson(xml);
		const items = obj.res.Item;
		let variables = '<Result>';
		let methodCode = '';

		for (let i = 0, len = items.length; i < len; i++) {
			if (items[i]['@attrs'].type === 'Variable') {
				variables +=
					'<Item type="Variable" id=' +
					items[i]['@attrs'].id +
					'>' +
					'<name>' +
					items[i].name +
					'</name>' +
					'<value>' +
					items[i].value +
					'</value>' +
					'</Item>';
			} else if (items[i]['@attrs'].type === 'Method') {
				methodCode = items[i]['method_code'];
			}
		}

		variables += '</Result>';

		return {
			code_to_check_pwd_policy: methodCode,
			vars_to_check_pwd_policy: variables
		};
	}

	const setFipsMode = function(passwordHashAlgorithm) {
		const arasObj = getAras();
		if (passwordHashAlgorithm === 'SHA256') {
			arasObj.setVariable('fips_mode', 'true');
		} else if (passwordHashAlgorithm === 'MD5') {
			arasObj.setVariable('fips_mode', null);
		}
	};

	const userMethods = {
		get id() {
			return storage.id;
		},
		get database() {
			return storage.database;
		},
		get type() {
			return storage.type;
		},
		get loginName() {
			return storage.loginName;
		},
		get authenticationType() {
			return storage.authenticationType;
		},
		login: function() {
			const arasObj = getAras();
			const serverUrl = arasObj.getServerURL();
			const args = {
				serverUrl: serverUrl,
				timezoneName: aras.getCommonPropertyValue(
					'systemInfo_CurrentTimeZoneName'
				)
			};

			const options = {
				url: serverUrl,
				method: 'ApplyItem',
				headers: {
					TIMEZONE_NAME: args.timezoneName
				}
			};
			ArasModules.soap(null, options);

			return userMethods
				.validate(serverUrl, args.timezoneName)
				.then(function(res) {
					const obj = ArasModules.xmlToJson(res);

					arasObj.setCommonPropertyValue(
						'ValidateUserXmlResult',
						res.parentNode.parentNode.xml
					);
					storage.loginName = obj.login_name;
					storage.database = obj.database;
					storage.authenticationType = obj.authentication_type;
					setFipsMode(obj.password_hash_algorithm);
					storage.id = obj.id;
					storage.type = obj['user_type'];
				})
				.catch(function(errorRes) {
					if (!errorRes) {
						return Promise.reject(
							arasObj.getResource(
								'',
								'aras_object.validate_user_failed_communicate_with_innovator_server'
							)
						);
					}

					let promise = null;
					const faultObj = faultToJSON(errorRes.responseXML);

					if (!faultObj) {
						return Promise.reject(
							arasObj.getResource(
								'',
								'aras_object.validate_user_wrong_innovator_sever_response'
							)
						);
					}

					const faultCode = faultObj.faultcode;

					if (faultCode === passwordExpiredConst) {
						promise = userMethods.errorHandlers.passwordExpired(faultObj, args);
					}

					return (
						promise ||
						Promise.reject(new SOAPResults(aras, errorRes.responseText))
					);
				});
		},
		validate: function(serverUrl, timezoneName) {
			const options = {
				url: serverUrl,
				method: 'ValidateUser',
				async: true,
				headers: {
					TIMEZONE_NAME: timezoneName
				}
			};

			const arasObj = getAras();
			Object.assign(
				options.headers,
				arasObj.OAuthClient.getAuthorizationHeader()
			);

			return ArasModules.soap('', options);
		},
		errorHandlers: {
			passwordExpired: function(faultObj, args) {
				const arasObj = getAras();
				const messageObj = faultObj.detail.message;
				const messages = Array.isArray(messageObj) ? messageObj : [messageObj];
				let passwordValidationInfo;
				let passwordHashAlgorithm;
				messages.forEach(function(element) {
					if ('key' in element['@attrs']) {
						if (element['@attrs'].key === 'password_validation_info') {
							passwordValidationInfo = element;
						}
						if (element['@attrs'].key === 'password_hash_algorithm') {
							passwordHashAlgorithm = element;
						}
					}
				});
				let data = {};

				if (passwordValidationInfo) {
					data = getPasswordPolicies(passwordValidationInfo['@attrs'].value);
				}

				if (passwordHashAlgorithm) {
					setFipsMode(passwordHashAlgorithm['@attrs'].value);
				}

				data.validationCallback = function(oldPasswordHash, newPasswordHash) {
					const requestData =
						'<old_password>' +
						oldPasswordHash +
						'</old_password>' +
						'<new_password>' +
						newPasswordHash +
						'</new_password>';

					const options = {
						url: args.serverUrl,
						method: 'ChangeUserPassword',
						async: true
					};

					const handleError = function(errorRes) {
						const item = arasObj.newIOMItem();
						item.loadAML(errorRes.responseText);
						return ArasModules.Dialog.alert(item.getErrorString()).then(
							function() {
								return false;
							}
						);
					};

					return ArasModules.soap(requestData, options)
						.then(function() {
							return true;
						})
						.catch(handleError);
				};

				return showDialog('passwordExpired', data).then(function(
					newPasswordHash
				) {
					if (newPasswordHash === undefined) {
						return Promise.reject(
							arasObj.getResource('', 'aras_object.new_password_not_set')
						);
					}

					return userMethods.login();
				});
			}
		}
	};

	ArasCore = Object.assign(ArasCore, { user: userMethods });
	window.ArasCore = window.ArasCore || ArasCore;
})(window.ArasCore || {});

/** ..\Modules\aras\dialogs\properties.js **/
(function(externalParent) {
	if (!(window.ArasModules && window.ArasModules.Dialog)) {
		return;
	}
	let aras;
	let dialogNode;
	let itemTypeName;
	let itemNode;
	let itemTypeNode;

	function getItemId(isItemId) {
		const isVersionable =
			aras.getItemProperty(itemTypeNode, 'is_versionable') === '1';
		return aras.getItemProperty(
			itemNode,
			isVersionable && !isItemId ? 'config_id' : 'id'
		);
	}

	function copyToclipboard(text, message) {
		if (aras.utils.isClipboardSupported()) {
			ArasModules.copyTextToBuffer(text, dialogNode);
			const notify = aras.getNotifyByContext(window);
			notify(message, { container: dialogNode });
		} else {
			aras.AlertError(aras.getResource('', 'clipboardmanager.use_ctrl_c'));
		}
	}

	function copyUrl(option, isItemId) {
		const text =
			aras.getInnovatorUrl() +
			'?StartItem=' +
			itemTypeName +
			':' +
			getItemId(isItemId) +
			(option ? ':' + option : '');
		copyToclipboard(
			text,
			aras.getResource('', 'common.copy_notification_link')
		);
	}

	function urlEventHandler(e) {
		const copyObj = {
			latest: copyUrl.bind(null, 'current'),
			'copy-url': copyUrl.bind(null, '', true),
			'latest-released': copyUrl.bind(null, 'released')
		};

		const cssSelector = Object.keys(copyObj)
			.map(function(dataAction) {
				return '*[data-action="' + dataAction + '"]';
			})
			.join(',');

		const targetNode = e.target.closest(cssSelector);
		if (
			!targetNode ||
			targetNode.classList.contains('aras-list-item_disabled')
		) {
			return;
		}
		copyObj[targetNode.dataset.action]();
	}

	function createUrlButtons(container, copyButton) {
		const urlButtonsContainer = document.createElement('div');
		urlButtonsContainer.classList.add('url-buttons-container');
		const copyUrlButton = document.createElement('button');
		copyUrlButton.classList.add('aras-btn', 'copy-url-btn');
		copyUrlButton.textContent = aras.getResource('', 'common.copy_link');
		copyUrlButton.dataset.action = 'copy-url';
		const dropdownContainer = document.createElement('aras-dropdown');
		dropdownContainer.classList.add('aras-dropdown-container');
		dropdownContainer.setAttribute('position', 'bottom-left');
		const dropdownButton = document.createElement('div');
		dropdownButton.classList.add(
			'aras-btn',
			'copy-url-dropdown-btn',
			'aras-icon-arrow',
			'aras-icon-arrow_down'
		);
		dropdownButton.setAttribute('dropdown-button', '');
		const dropdownBox = document.createElement('div');
		dropdownBox.classList.add('aras-dropdown');
		const optionsList = document.createElement('ul');
		optionsList.classList.add('aras-list');
		copyButton.classList.add('copy-id-button');
		urlButtonsContainer.appendChild(copyButton);
		urlButtonsContainer.appendChild(dropdownContainer);
		dropdownContainer.appendChild(copyUrlButton);
		dropdownContainer.appendChild(dropdownButton);
		dropdownContainer.appendChild(dropdownBox);
		dropdownBox.appendChild(optionsList);

		const li = document.createElement('li');
		li.classList.add('aras-list-item');
		if (aras.getItemProperty(itemTypeNode, 'is_versionable') === '0') {
			li.classList.add('aras-list-item_disabled');
		}
		const labelNode = document.createElement('li');
		labelNode.classList.add('aras-list-item__label');
		labelNode.textContent = aras.getResource('', 'common.copy_link_latest');
		li.appendChild(labelNode);
		li.dataset.action = 'latest';
		optionsList.appendChild(li.cloneNode(true));
		li.querySelector('.aras-list-item__label').textContent = aras.getResource(
			'',
			'common.copy_link_latest_released'
		);
		li.dataset.action = 'latest-released';
		optionsList.appendChild(li);

		container.appendChild(urlButtonsContainer);
		urlButtonsContainer.addEventListener('click', urlEventHandler);
	}

	const properties = function(item, itemType, options) {
		options = options || {};
		aras = options.aras || window.aras;
		if (!aras) {
			return Promise.reject();
		}

		itemTypeName = aras.getNodeElement(itemType, 'name');
		itemNode =
			aras.getItemById(itemTypeName, item.getAttribute('id'), 0) || item;
		itemTypeNode = itemType;
		const itemTypeLabel = aras.getNodeElement(itemType, 'label');
		const dialogTitle =
			options.title ||
			aras.getResource(
				'',
				'propsdialog.item_type_label__item_keyed_name__properties',
				itemTypeLabel,
				aras.getKeyedNameEx(item)
			);
		const propsDialog = new ArasModules.Dialog('html', {
			title: dialogTitle
		});
		dialogNode = propsDialog.dialogNode;
		const contentNode = propsDialog.contentNode;
		dialogNode.classList.add('aras-dialog_properties');
		const tableNode = document.createElement('div');
		tableNode.classList.add('properties-table-container');
		contentNode.appendChild(tableNode);

		const infoTable = aras.uiDrawItemInfoTable(itemType);
		tableNode.innerHTML = infoTable;

		aras.uiPopulateInfoTableWithItem(
			item,
			propsDialog.dialogNode.ownerDocument
		);
		const copyButton = document.createElement('button');
		copyButton.classList.add('aras-btn');

		const copyButtonTextResourse = 'common.copy_id';
		createUrlButtons(contentNode, copyButton);

		copyButton.textContent = aras.getResource('', copyButtonTextResourse);
		copyButton.addEventListener('click', function() {
			copyToclipboard(
				getItemId(true),
				aras.getResource('', 'common.copy_notification_id')
			);
		});

		propsDialog.show();

		ArasModules.dropdownButton(
			contentNode.querySelector('.aras-dropdown-container'),
			{ buttonSelector: '.copy-url-dropdown-btn' }
		);
		return propsDialog.promise;
	};

	externalParent.Dialogs = externalParent.Dialogs || {};
	externalParent.Dialogs.properties = properties;
	window.ArasCore = window.ArasCore || externalParent;
})(window.ArasCore || {});

/** ..\Modules\aras\dialogs\about.js **/
(function(externalParent) {
	if (!window.ArasModules.Dialog) {
		return;
	}

	const about = function() {
		const dialogTitle = aras.getResource(
			'',
			'aras_object.about_aras_innovator'
		);
		const data = aras.aboutData;
		const aboutDialog = new ArasModules.Dialog('html', {
			title: dialogTitle
		});

		const content = document.createElement('div');
		const logoContent = document.createElement('div');
		const logoImage = document.createElement('img');
		const version = document.createElement('p');
		const msBuild = version.cloneNode();
		const supportLink = version.cloneNode();
		const arasLink = version.cloneNode();
		const copyright = version.cloneNode();
		const okBtn = document.createElement('button');
		let link = document.createElement('a');
		logoImage.src = aras.getBaseURL('/images/aras-innovator.svg');
		logoContent.appendChild(logoImage);
		content.appendChild(logoContent);
		content.appendChild(version);
		content.appendChild(msBuild);
		content.appendChild(supportLink);
		content.appendChild(arasLink);
		content.appendChild(copyright);
		content.classList.add('aras-dialog_about__content');

		version.textContent =
			'Aras Innovator Version ' +
			data.version.revision +
			'  Build: ' +
			data.version.build;
		msBuild.textContent = 'MS Build Number: ' + data.msBuildNumber;
		link.href = link.textContent = 'http://www.aras.com/support/';
		link.target = '_blank';
		link.classList.add('aras-link');
		supportLink.textContent = 'For support please go to ';
		supportLink.appendChild(link);

		link = link.cloneNode(true);
		link.href = link.textContent = 'http://www.aras.com';
		arasLink.textContent = 'Visit us on-line at ';
		arasLink.appendChild(link);

		copyright.textContent = data.copyright;

		okBtn.autofocus = true;
		okBtn.classList.add('aras-btn', 'aras-btn-right');
		okBtn.textContent = aras.getResource('', 'common.ok');
		okBtn.addEventListener('click', aboutDialog.close.bind(aboutDialog));

		aboutDialog.dialogNode.appendChild(content);
		aboutDialog.dialogNode.appendChild(okBtn);
		aboutDialog.dialogNode.classList.add('aras-dialog_about');

		aboutDialog.show();

		return aboutDialog.promise;
	};

	externalParent.Dialogs = externalParent.Dialogs || {};
	externalParent.Dialogs.about = about;
	window.ArasCore = window.ArasCore || externalParent;
})(window.ArasCore || {});

/** ..\Modules\aras\dialogs\selectPackageDefinition.js **/
(function(externalParent) {
	if (!window.ArasModules.Dialog) {
		return;
	}

	const selectPackageDefinition = function(arrayOfPackage) {
		const dialogTitle = aras.getResource(
			'',
			'item_methods.add_selected_items_to_a_package'
		);

		const selectPackageDialog = new ArasModules.Dialog('html', {
			title: dialogTitle
		});

		const selectPackageContainer = document.createElement('div');
		const selectPackage = document.createElement('div');
		const selectElement = document.createElement('select');
		if (arrayOfPackage.length > 0) {
			selectElement.add(
				new Option(aras.getResource('', 'item_methods.select_package'))
			);
		}
		selectElement.add(
			new Option(aras.getResource('', 'item_methods.create_new'), 'create new')
		);
		arrayOfPackage.forEach(function(item, arrayOfPackage) {
			selectElement.add(new Option(item));
		});

		selectPackage.appendChild(selectElement);
		selectPackageContainer.textContent = aras.getResource(
			'',
			'item_methods.selected_package_from_list'
		);
		selectPackageContainer.appendChild(selectPackage);

		const buttonsContainer = document.createElement('div');
		const okButton = document.createElement('button');
		okButton.textContent = aras.getResource('', 'common.ok');
		okButton.addEventListener(
			'click',
			function() {
				this.close(selectElement.value);
			}.bind(selectPackageDialog)
		);
		okButton.classList.add('aras-btn');
		const cancelButton = document.createElement('button');
		cancelButton.textContent = aras.getResource('', 'common.cancel');
		cancelButton.classList.add('aras-btn', 'btn_cancel');
		cancelButton.addEventListener(
			'click',
			selectPackageDialog.close.bind(selectPackageDialog, null)
		);
		buttonsContainer.appendChild(okButton);
		buttonsContainer.appendChild(cancelButton);

		selectPackageDialog.contentNode.appendChild(selectPackageContainer);
		selectPackageDialog.contentNode.appendChild(buttonsContainer);
		selectPackageDialog.dialogNode.classList.add(
			'aras-dialog_select-package-definition',
			'aras-form'
		);

		selectPackageDialog.show();

		return selectPackageDialog.promise;
	};

	externalParent.Dialogs = externalParent.Dialogs || {};
	externalParent.Dialogs.selectPackageDefinition = selectPackageDefinition;
	window.ArasCore = window.ArasCore || externalParent;
})(window.ArasCore || {});

/** ..\Modules\aras\dialogs\createNewPackage.js **/
(function(externalParent) {
	if (!window.ArasModules.Dialog) {
		return;
	}

	const createNewPackage = function(arrayOfPackage) {
		const dialogTitle = aras.getResource('', 'item_methods.create_new_package');

		const createNewPacakgeDialog = new ArasModules.Dialog('html', {
			title: dialogTitle
		});

		const packageNameContainer = document.createElement('div');
		const packageNameLabel = document.createElement('label');
		packageNameLabel.textContent = aras.getResource(
			'',
			'item_methods.package_name'
		);
		packageNameLabel.classList.add('aras-dialog_create-new-package__label');
		const packageNameInput = document.createElement('input');
		packageNameInput.type = 'text';
		packageNameInput.placeholder = 'new name';
		packageNameInput.classList.add(
			'aras-dialog_create-new-package__main-content'
		);
		packageNameContainer.appendChild(packageNameLabel);
		packageNameContainer.appendChild(packageNameInput);

		const dependencyContainer = document.createElement('div');
		const dependencyLabel = document.createElement('label');
		dependencyLabel.textContent = aras.getResource(
			'',
			'item_methods.dependency'
		);
		dependencyLabel.classList.add('aras-dialog_create-new-package__label');
		const dependencyPackageSelect = document.createElement('select');
		dependencyPackageSelect.size = 11;
		dependencyPackageSelect.multiple = true;
		arrayOfPackage.forEach(function(item, arrayOfPackage) {
			dependencyPackageSelect.add(new Option(item));
		});
		dependencyPackageSelect.classList.add(
			'aras-dialog_create-new-package__main-content'
		);
		dependencyContainer.appendChild(dependencyLabel);
		dependencyContainer.appendChild(dependencyPackageSelect);
		dependencyContainer.classList.add(
			'aras-dialog_create-new-package__dependency-container'
		);

		const buttonsContainer = document.createElement('div');
		const okButton = document.createElement('button');
		okButton.textContent = aras.getResource('', 'common.ok');
		okButton.classList.add('aras-btn');
		okButton.addEventListener(
			'click',
			function() {
				const objectPackage = { packageName: packageNameInput.value };
				const dependency = [];
				for (let i = 0; i < dependencyPackageSelect.options.length; i++) {
					if (dependencyPackageSelect.options[i].selected) {
						dependency.push(dependencyPackageSelect.options[i].value);
					}
				}
				objectPackage.dependency = dependency;
				this.close(objectPackage);
			}.bind(createNewPacakgeDialog)
		);
		const cancelButton = document.createElement('button');
		cancelButton.textContent = aras.getResource('', 'common.cancel');
		cancelButton.addEventListener(
			'click',
			createNewPacakgeDialog.close.bind(createNewPacakgeDialog, null)
		);
		cancelButton.classList.add('aras-btn', 'btn_cancel');
		buttonsContainer.appendChild(okButton);
		buttonsContainer.appendChild(cancelButton);

		createNewPacakgeDialog.contentNode.appendChild(packageNameContainer);
		createNewPacakgeDialog.contentNode.appendChild(dependencyContainer);
		createNewPacakgeDialog.contentNode.appendChild(buttonsContainer);
		createNewPacakgeDialog.contentNode.classList.add('aras-form');
		createNewPacakgeDialog.dialogNode.classList.add(
			'aras-dialog_create-new-package'
		);

		createNewPacakgeDialog.show();

		return createNewPacakgeDialog.promise;
	};

	externalParent.Dialogs = externalParent.Dialogs || {};
	externalParent.Dialogs.createNewPackage = createNewPackage;
	window.ArasCore = window.ArasCore || externalParent;
})(window.ArasCore || {});

/** ..\Modules\aras\searchConverter.js **/
(function(externalParent) {
	const normalizeFloatDecimal = function(value) {
		const numberToString = window.ArasModules.intl.number.toString;
		const parseFloat = window.ArasModules.intl.number.parseFloat;

		const numberValue = parseFloat(value);
		const stringValue = isNaN(numberValue)
			? value
			: numberToString(numberValue);
		return stringValue;
	};

	const generateJsonNode = function(criteria, condition, type) {
		let value = criteria;
		if (type === 'decimal' || type === 'float') {
			value = normalizeFloatDecimal(criteria);
		}
		return {
			'@attrs': {
				condition: condition
			},
			'@value': value
		};
	};

	const parseNumberQuery = function(criterias, propName, type) {
		return criterias.reduce(function(acc, criteria) {
			acc[propName] = acc[propName] || [];
			const criteriaParts = criteria.split(/(\.{3}|>=|<=|>|<)/);
			if (criteriaParts.length !== 3) {
				acc[propName].push(generateJsonNode(criteria, 'eq', type));
				return acc;
			}
			if (criteriaParts[0].length === 0) {
				switch (criteriaParts[1]) {
					case '>=':
						acc[propName].push(generateJsonNode(criteriaParts[2], 'ge', type));
						break;
					case '<=':
						acc[propName].push(generateJsonNode(criteriaParts[2], 'le', type));
						break;
					case '>':
						acc[propName].push(generateJsonNode(criteriaParts[2], 'gt', type));
						break;
					case '<':
						acc[propName].push(generateJsonNode(criteriaParts[2], 'lt', type));
						break;
				}
			} else if (criteriaParts[1] === '...') {
				acc.AND = acc.AND || [];
				const rangeCriteria = {};
				rangeCriteria[propName] = [
					generateJsonNode(criteriaParts[0], 'ge', type),
					generateJsonNode(criteriaParts[2], 'le', type)
				];
				acc.AND.push(rangeCriteria);
			}
			return acc;
		}, {});
	};

	const simpleToAml = function(criteria, propName, type) {
		const criterias = criteria.split('|');

		let jsonForParse;
		if (
			type === 'float' ||
			type === 'decimal' ||
			type === 'integer' ||
			type === 'ubigint' ||
			type === 'global_version'
		) {
			jsonForParse = parseNumberQuery(criterias, propName, type);
		} else {
			jsonForParse = criterias.reduce(function(acc, criteria) {
				acc[propName].push(generateJsonNode(criteria, 'eq', type));
				return acc;
			}, {});
		}

		if (criterias.length > 1) {
			jsonForParse = {
				OR: jsonForParse
			};
		}

		return window.ArasModules.jsonToXml(jsonForParse);
	};

	const searchConverter = {
		simpleToAml: simpleToAml
	};
	externalParent = Object.assign(externalParent, {
		searchConverter: searchConverter
	});
	window.ArasCore = window.ArasCore || externalParent;
})(window.ArasCore || {});

/** ModalDialogHelper.js **/
function ModalDialogHelper(baseUrl) {
	this.baseUrl = baseUrl;
}

ModalDialogHelper.prototype._getOptionsStr = function(options) {
	options = Object.assign({dialogWidth: 250, dialogHeight: 100, center: true}, options || {});

	if (!options.dialogLeft && !options.dialogTop) {
		options.dialogLeft = (screen.width - options.dialogWidth) / 2;
		options.dialogTop = (screen.height - options.dialogHeight) / 2;
	}

	return ''.concat(options.dialogWidth ? 'dialogWidth:' + options.dialogWidth + 'px;' : '', '',
		options.dialogHeight ? 'dialogHeight:' + options.dialogHeight + 'px; ' : ' ',
		options.dialogLeft ? 'dialogLeft:' + options.dialogLeft + 'px;' : '', ' ',
		options.dialogTop ? 'dialogTop:' + options.dialogTop + 'px;' : '', ' ',
		'center:', options.center ? 'yes' : 'no', '; ',
		'resizable:', options.resizable ? 'yes' : 'no', '; ',
		'status:', options.status ? 'yes' : 'no', '; ',
		'scroll:', options.scroll ? 'yes' : 'no', '; ',
		'help:', options.help ? 'yes' : 'no', ';');
};

ModalDialogHelper.prototype.show = function(type, aWindow, params, options, file, callbacks) {
	if (type === 'DefaultModal') {
		file = file || '';
		params = params || {};
		params.opener = aWindow;
		// fix jshint rule scripturl
		var url = file.indexOf(['javascript', ':'].join('')) === 0 ? file : this.baseUrl + file;
		return aWindow.showModalDialog(url, params, this._getOptionsStr(options));
	}

	var callback  = params.callback || function() {};
	params.callback = function() {};

	var args = Object.assign({content: file, type: type}, params, options);

	aWindow.dialogArguments = args;
	var dialog = aWindow.ArasModules.Dialog.show('iframe', args);
	if (options && (typeof(options.top) === 'number' || typeof(options.top) === 'string') &&
		(typeof(options.left) === 'number' || typeof(options.left) === 'string')) {
		dialog.move(options.left, options.top);
	}
	dialog.content = dialog.dialogNode.querySelector('.aras-dialog__iframe');

	dialog.promise.then(function(res) {
		res = res || dialog.result;
		dialog.result = res;
		if (callbacks && callbacks.oncancel) {
			callbacks.oncancel(dialog);
		}
		callback(res);
		aWindow.dialogArguments = null;
	});
	if (callbacks && callbacks.onload) {
		callbacks.onload(dialog);
	}
};

/** WebFile.js **/
function WebFile() {
	/// <summary>
	///	 WebFile keeps static methods for working with files on Web.
	///  Is planned as something like System.IO.File class in .NET Framework.
	/// </summary>
	/// <summary locid="M:J#Aras.Client.JS.WebFile.#ctor">
	/// This is summary for constructor.
	/// </summary>
}

WebFile.Exists = function WebFileExists(url) {
	/// <summary locid="M:J#Aras.Client.JS.WebFile.Exists">
	///  Checks wheather resource under specified URL is availiable or not.
	///  Sends HEAD request to the server and analyses response.
	/// <param locid="M:J#Aras.Client.JS.WebFile.Exists" name="url" type="string" mayBeNull="false">
	///	 URL of resource beeeing checked.
	/// </param>
	/// </summary>
	/// <returns type="Boolean">Returs "true" if resource under specified URL is available and "false" otherwise.</returns>
	var xmlhttp = new XMLHttpRequest();
	xmlhttp.open('HEAD', url, false);
	xmlhttp.send();
	return !(xmlhttp.status == 404 || xmlhttp.statusText == 'Not Found');
};

/** enumerations.js **/
var Enums = {};

Enums.UrlType = {'None': 0, 'SecurityToken': 1};
Enums.SortType = {'Ascending': 0, 'Descending': 1};
Enums.CheckinManagerFlags = {'None': 0, 'UnlockAfterCheckin': 1};
Enums.CheckoutManagerFlags = {'None': 0, 'UseTransactions': 1};

/** ClientControlsFactoryHelper.js **/
function ClientControlsFactoryHelper() {
}

ClientControlsFactoryHelper.prototype.getFactory = function ClientControlsFactoryHelperGetFactory(aWindow) {
	return new aWindow.ClientControlsFactory();
};

/** ShortcutsHelperFactory.js **/
// jshint ignore:line
/*global KeyboardEvent, window*/
(function() {
	'use strict';
	var ShortcutListener = function(shortcut) {
		this.callbacks = [];
		this.shortcut = shortcut;
	};

	ShortcutListener.prototype.addCallback = function(callback) {
		this.callbacks.push(callback);
	};

	ShortcutListener.prototype.removeCallback = function(callback) {
		this.callbacks = this.callbacks.filter(function(item) {
			if (item === callback) {
				return false;
			}
			return true;
		});
	};

	ShortcutListener.prototype.preventBlur = function() {
		return !this.callbacks.some(function(item) {
			return (true !== item.preventBlur);
		});
	};

	ShortcutListener.prototype.stopPropagation = function() {
		return !this.callbacks.some(function(item) {
			return (true !== item.stopPropagation);
		});
	};

	ShortcutListener.prototype.preventDefault = function() {
		return this.callbacks.some(function(item) {
			return (false !== item.preventDefault);
		});
	};

	ShortcutListener.prototype.callback = function(state) {
		var callback;
		var callbackResult;
		var index = 0;
		for (index; index < this.callbacks.length; index += 1) {
			callback = this.callbacks[index];
			if (callback.hasOwnProperty('enabled') && !callback.enabled) {
				continue;
			}
			if (state.useCapture === callback.useCapture) {
				callbackResult = callback.context ? callback.handler.call(callback.context, state) : callback.handler(state);
				if (!callbackResult) {
					return false;
				}
			}
		}
		return true;
	};

	var specialKeys = {
		8: 'backspace',
		9: 'tab',
		13: 'enter',
		19: 'pause',
		20: 'capslock',
		27: 'esc',
		32: 'space',
		33: 'pageup',
		34: 'pagedown',
		35: 'end',
		36: 'home',
		37: 'left',
		38: 'up',
		39: 'right',
		40: 'down',
		45: 'insert',
		46: 'delete',
		96: '0',
		97: '1',
		98: '2',
		99: '3',
		100: '4',
		101: '5',
		102: '6',
		103: '7',
		104: '8',
		105: '9',
		106: '*',
		107: '+',	// '+' from Num keyboard
		109: '-',	// '-' from Num keyboard
		110: '.',
		111: '/',
		112: 'f1',
		113: 'f2',
		114: 'f3',
		115: 'f4',
		116: 'f5',
		117: 'f6',
		118: 'f7',
		119: 'f8',
		120: 'f9',
		121: 'f10',
		122: 'f11',
		123: 'f12',
		144: 'numlock',
		145: 'scroll',
		187: '+',
		188: '<',
		189: '-',
		190: '>',
		191: '/',
		192: '~',
		219: '[',
		221: ']'
	};

	var modifierKeys = {
		16: 'shift',
		17: 'ctrl',
		18: 'alt',
		224: 'meta',
		91: 'windows'
	};

	var shiftNums = {
		'`': '~',
		'1': '!',
		'2': '@',
		'3': '#',
		'4': '$',
		'5': '%',
		'6': '^',
		'7': '&',
		'8': '*',
		'9': '(',
		'0': ')',
		'-': '_',
		'=': '+',
		';': ': ',
		'\'': '"',
		',': '<',
		'.': '>',
		'/': '?',
		'\\': '|'
	};

	var parseEvent = function(event) {
		var character = specialKeys[event.which] || String.fromCharCode(event.which).toLowerCase();
		var modif = '';
		var shortcuts = [];
		// check combinations (alt|ctrl|shift+anything)
		if (event.altKey) {
			modif += 'alt+';
		}

		if (event.ctrlKey && aras.Browser.OSName !== 'MacOS') {
			modif += 'ctrl+';
		}

		// TODO: Need to make sure this works consistently across platforms
		if (event.metaKey && !event.ctrlKey) {
			//equate pressing meta to ctrl
			modif += 'ctrl+';
		}

		if (event.shiftKey) {
			modif += 'shift+';
		}

		shortcuts.push(modif + character);
		// "$" can be triggered as "Shift+4" or "Shift+$" or just "$"
		if ('shift+' === modif) {
			shortcuts.push(modif + shiftNums[character]);
			shortcuts.push(shiftNums[character]);
		}
		return shortcuts;
	};

	var ShortcutsHelper = function(aWindow) {
		var shortcutListeners = {};
		var isPreventDefault = false;
		var preventDefaultHandler = function(event) {
			if (isPreventDefault) {
				event.preventDefault();
				isPreventDefault = false;
			}
		};

		var getAvailableShortcuts = function(possibleShortcuts) {
			var signedShorcuts = Object.keys(shortcutListeners);
			return possibleShortcuts.filter(function(item) {
				if (-1 === signedShorcuts.indexOf(item)) {
					return false;
				}
				return true;
			});
		};

		var eventHandler = function(event, useCapture) {
			if (modifierKeys[event.which]) {
				return;
			}

			var possibleShortcuts = parseEvent(event);
			var activeElement = event.currentTarget.document.activeElement;
			var availableShortcuts = getAvailableShortcuts(possibleShortcuts);

			if (0 === availableShortcuts.length) {
				return;
			}
			var preventBlur = false;
			var preventDefault = true;
			var stopPropagation = false;
			var index = 0;
			var shortcutListener;
			var tmp;
			for (index; index < availableShortcuts.length; index += 1) {
				shortcutListener = shortcutListeners[availableShortcuts[index]];
				tmp = shortcutListener.preventBlur();
				if (tmp && !preventBlur) {
					preventBlur = true;
				}
				tmp = shortcutListener.preventDefault();
				if (!tmp && preventDefault) {
					preventDefault = false;
				}
				tmp = shortcutListener.stopPropagation();
				if (tmp && !stopPropagation) {
					stopPropagation = true;
				}
			}

			if (preventDefault) {
				event.preventDefault();
			}

			if (stopPropagation) {
				event.stopPropagation();
			}

			var shortcutState = {
				contentBlurable: activeElement && ['INPUT', 'SELECT', 'TEXTAREA'].indexOf(activeElement.tagName) !== -1,
				contentEditable: activeElement && ((activeElement.tagName === 'INPUT') ?
						['text', 'password'].indexOf(activeElement.type.toLowerCase()) !== -1 : ('TEXTAREA' === activeElement.tagName ? true : false)),
				useCapture: useCapture
			};
			//if an domNode has the focus then call  method  blur event to trigger
			//onchange event (the change event is fired for <input>, <select>, and <textarea> elements)
			if (!preventBlur && shortcutState.contentBlurable) {
				activeElement.blur();
			}

			//fix bug related on running setTimeout with function from other window in IE10
			var context = {availableShortcuts: availableShortcuts, shortcutListeners: shortcutListeners, shortcutState: shortcutState};
			event.currentTarget.setTimeout(event.currentTarget.Function(
					'var shortcut,\n' +
						'	sortcutListener,\n' +
						'	index = 0;\n' +
						'for (index; index < this.availableShortcuts.length; index += 1) {\n' +
						'	sortcutListener = this.shortcutListeners[this.availableShortcuts[index]];\n' +
						'	sortcutListener.callback(this.shortcutState);\n' +
						'}\n').bind(context),
					0);
		};

		var eventHandlerWithoutCapture = function(e) {
			eventHandler(e, false);
		};

		var eventHandlerWithCapture = function(e) {
			eventHandler(e, true);
		};

		//subscribe to keydown event
		aWindow.addEventListener('keypress', preventDefaultHandler, false);
		aWindow.addEventListener('keydown', eventHandlerWithoutCapture, false);
		aWindow.addEventListener('keydown', eventHandlerWithCapture, true);

		this.subscribe = function(callback, subcribeChild) {
			var shortcut = callback.shortcut.toLowerCase();
			if (undefined === callback.useCapture) {
				callback.useCapture = false;
			}
			if (!shortcutListeners[shortcut]) {
				shortcutListeners[shortcut] = new ShortcutListener(shortcut);
			}
			shortcutListeners[shortcut].addCallback(callback);
			if (subcribeChild) {
				var frames = aWindow.document.querySelectorAll('frame, iframe');
				var factory = new window.ShortcutsHelperFactory();
				var index = 0;
				var currFrame;
				var frameLoadHandler = function() {
					factory.getInstance(this.contentWindow).subscribe(callback, subcribeChild);
				};
				for (index; index < frames.length; index += 1) {
					currFrame = frames[index];
					currFrame.addEventListener('load', frameLoadHandler, false);
					(function(currFrame) {// jshint ignore:line
						var windowUnloadHandler = function() {
							currFrame.removeEventListener('load', frameLoadHandler);
							this.removeEventListener('unload', windowUnloadHandler);
						};
						aWindow.addEventListener('unload', windowUnloadHandler, false);
					})(currFrame);// jshint ignore:line
					try {
						var tmp = currFrame.contentDocument;
					} catch (ex) {
						return;	//"no such interface supported" for "xDomain" in frames
					}
					if (currFrame.contentDocument && 'complete' === currFrame.contentDocument.readyState) {
						frameLoadHandler.call(currFrame);
					}
				}
			}
		};

		this.unsubscribe = function(callback, unsubcribeChild) {
			var shortcutListener = shortcutListeners[callback.shortcut.toLowerCase()];
			if (shortcutListener) {
				shortcutListener.removeCallback(callback);
			}
			if (unsubcribeChild) {
				var frames = aWindow.document.querySelectorAll('frame, iframe');
				var factory = new window.ShortcutsHelperFactory();
				var index = 0;
				var currFrame;
				for (index; index < frames.length; index += 1) {
					currFrame = frames[index];
					factory.getInstance(currFrame.contentWindow).unsubscribe(callback, unsubcribeChild);
				}
			}
		};

		this.unsubscribeWindow = function(aWindow) {
			var listener;
			var callback;
			for (var sIndex in shortcutListeners) {
				listener = shortcutListeners[sIndex];
				if (listener.callbacks) {
					for (var lIndex = 0; lIndex < listener.callbacks.length; lIndex++) {
						callback = listener.callbacks[lIndex];
						if (callback.context == aWindow) {
							this.unsubscribe(callback);
						}
					}
				}
			}
		};

		this.dispose = function() {
			aWindow.removeEventListener('keypress', preventDefaultHandler);
			aWindow.removeEventListener('keydown', eventHandlerWithoutCapture);
			aWindow.removeEventListener('keydown', eventHandlerWithCapture);
		};
	};

	window.ShortcutsHelperFactory = function() {
	};

	window.ShortcutsHelperFactory.prototype.getInstance = function(aWindow) {
		if (!aWindow.ARAS_SHORTCUTS_HELPER || !(aWindow.ARAS_SHORTCUTS_HELPER instanceof ShortcutsHelper)) {
			aWindow.ARAS_SHORTCUTS_HELPER = new ShortcutsHelper(aWindow);
			var unsibscribeHandler = function() {
				aWindow.removeEventListener('unload', unsibscribeHandler);
				aWindow.ARAS_SHORTCUTS_HELPER.unsubscribeWindow(aWindow);
				aWindow.ARAS_SHORTCUTS_HELPER.dispose();
			};

			aWindow.addEventListener('unload', unsibscribeHandler);
		}
		return aWindow.ARAS_SHORTCUTS_HELPER;
	};
}());

/** Aras\Client\Controls\Public\Vault.js **/
function Vault(vaultInstance, fakeMethodHandler) {
	/// <summary>
	/// "aras.vault" instance of the class can be used in custom JavaScript code.
	/// Vault provides batch file uploading/downloading capabilities together with related
	/// file manipulation routines.
	/// </summary>
	/// <remarks>
	/// It has user friendly interface, displays a progress bar during time consuming upload/download
	/// process and has warning/error messages system to inform the user about any collisions.<br/>
	/// User has a possibility to add/remove files to the batch list, rename files and folders,
	/// cancel current job.<br/>
	/// User may select files from both local and network-mapped folders, optionally including all
	/// sub-folders.
	/// Additionally, he can enter any valid network path and browse it in the file selection dialog.
	/// <p>
	/// File transfer works over http, SSL (https) with or without proxy. This is achieved
	/// by using browser's native connection classes.<br/>
	/// And the most attractive feature is the possibility to upload huge files (unlimited file size)
	/// with no timeouts or memory leacks (known java bug).<br/>
	/// We use all available network traffic, so the transfer will go as fast as your LAN/WAN allows.<br/>
	/// You can submit your form data together with the file. It is usually required to send the state
	/// information back to the server.
	/// </p>
	/// <p>
	/// What else can I do with Vault applet that I can't with a usual FILE form input field?
	/// - Well, you can control, filter and preprocess the file list that user has selected.
	/// You can enable or disable to transfer some file types basing on your application logic,
	/// and you can collect additional information related to those files.
	/// And finally, you don't need to reload your page while you transferring the files.
	/// </p>
	/// <p>
	/// We use the standard "multipart/form-data" content encoding, so the applet is compatible
	/// with any server-side uploading component.
	/// The quality of the server-side component as well as the hard-drive performance
	/// will also affect the resulting transfer rate.
	/// </p>
	/// </remarks>

	this.vault = vaultInstance;

	this.init = function vault_init() {
		var doFakeVault = false, fakeVaultMethod;
		if (!this.vault) {
			doFakeVault = true;
			this.vault = {};
			fakeVaultMethod = function() {
				if (fakeMethodHandler) {
					fakeMethodHandler();
				}
			};
		}

		for (var funcName in this) {
			var obj = this[funcName];
			var firstChar = funcName.charAt(0);

			if (typeof(obj) == 'function' && !this.hasOwnProperty(funcName) && firstChar.toLowerCase() == firstChar) {
				var newFuncName = firstChar.toUpperCase() + funcName.slice(1);
				this[newFuncName] = obj;
				if (doFakeVault) {
					this.vault[newFuncName] = this.vault[funcName] = fakeVaultMethod;
				}
			}
		}
	};
}

Vault.prototype.getOS = function() {
	/// <summary>
	/// Returns the string defining the operating system the applet is running on.
	/// Is not supported. Use navigator.userAgent to detect Windows platform.
	/// </summary>
	throw new Error('The method "getOS" from Vault API is not supported');
};

Vault.prototype.mkDir = function() {
	/// <summary>
	/// Creates a directory structure on the local file system.<br/>
	/// Mode: download.
	/// Is not supported because it works directly with files system
	/// </summary>
	throw new Error('The method "mkDir" from Vault API is not supported');
};

Vault.prototype.fileCreateWithSaveAsDialog = function() {
	/// <summary>
	/// Creates or overwrites the specified file and show SaveAsDialog.
	/// Is not supported because it works directly with files system
	/// </summary>
	throw new Error('The method "fileCreateWithSaveAsDialog" from Vault API is not supported');
};

Vault.prototype.fileExists = function() {
	/// <summary>
	/// Gets a value indicating whether a file exists.
	/// Is not supported because it works directly with files system
	/// </summary>
	throw new Error('The method "fileExists" from Vault API is not supported');
};

Vault.prototype.directoryExists = function() {
	/// <summary>
	/// Gets a value indicating whether the directory exists.
	/// Is not supported because it works directly with files system
	/// </summary>
	throw new Error('The method "directoryExists" from Vault API is not supported');
};

Vault.prototype.getParentDir = function() {
	/// <summary>
	/// Gets parent directory.
	/// Is not supported because it works directly with files system
	/// </summary>
	throw new Error('The method "getParentDir" from Vault API is not supported');
};

Vault.prototype.setWorkingDir = function() {
	/// <summary>
	/// Sets the local working directory for the applet (where files are to be downloaded into).<br/>
	/// Initially working directory can be initialized from {@link #pWORKINGDIR pWORKINGDIR} parameter.<br/>
	/// Mode: download.
	/// Is not supported because it works directly with files system
	/// </summary>
	throw new Error('The method "setWorkingDir" from Vault API is not supported');
};

Vault.prototype.setFileName = function() {
	/// <summary>
	/// Sets the Filename property. This can be used to set the file name as an alternative to the SelectFile() method.
	/// Is not supported because it works directly with files system
	/// </summary>
	throw new Error('The method "setFileName" from Vault API is not supported');
};

Vault.prototype.setClientData = function(name, value_Renamed) {
	/// <summary>
	/// Set userdata (form fields) for uploading.<br/>
	/// Mode: upload.
	/// </summary>
	/// <param name="name" type="string"></param>
	/// <param name="value_Renamed" type="string"></param>
	return this.vault.setClientData(name, value_Renamed);
};

Vault.prototype.getClientData = function(name) {
	/// <summary>
	/// Gets userdata (form fields) for uploading.
	/// </summary>
	/// <param name="name" type="string"></param>
	/// <returns>string</returns>
	return this.vault.getClientData(name);
};

Vault.prototype.selectFolder = function() {
	/// <summary>
	/// Displays a folder selection dialog box that allows the user to browse the local file system and select a folder.
	/// Filename property is set to null
	/// Is not supported because it works directly with files system
	/// </summary>
	throw new Error('The method "selectFolder" from Vault API is not supported');
};

Vault.prototype.selectSavePath = function() {
	/// <summary>
	/// Displays a SaveFile dialog box, that allows to browse local file system and select a file path for "save" operation.
	/// initialPath parameter used to setup initial directory and filename.
	/// dialogTitle string will be displayed in title bar.
	/// Is not supported because it works directly with files system
	/// </summary>
	throw new Error('The method "selectSavePath" from Vault API is not supported');
};

Vault.prototype.selectFile = function() {
	/// <summary>
	/// Displays a file selection dialog box that allows the user to browse the local file system and select a file.
	/// The WorkingDir property for the applet is also set if the user browses to a directory.
	/// The working directory for the dialog box is initialized to the working directory for the applet.
	/// </summary>
	/// <returns>
	/// string. Returns a string representing the fully qualified path to the file selected and sets the Filename property for the applet.
	/// </returns>
	return this.vault.selectFile();
};

Vault.prototype.getFileChecksum = function(fileName) {
	/// <summary>
	/// Gets checksum of the current file.
	/// </summary>
	/// <param name="fileName" type="string"></param>
	/// <returns>string</returns>
	return this.vault.getFileChecksum(fileName);
};

Vault.prototype.addFileToDownloadList = function() {
	/// <summary>
	/// Add the specified file URL to the download list.
	/// Is not supported because multiple downloading cannot be performed without extensions
	/// </summary>
	throw new Error('The method "addFileToDownloadList" from Vault API is not supported');
};

Vault.prototype.addFileToList = function(fileID, filename) {
	/// <summary>
	/// Add the specified file URL to the fileList.
	/// </summary>
	/// <param name="fileID" type="string"></param>
	/// <param name="filename" type="string"></param>
	/// <returns>bool</returns>
	return this.vault.addFileToList(fileID, filename);
};

Vault.prototype.sendFile = function() {
	/// <summary>
	/// Send file from clientData to specified url from working directory.
	/// Is not supported because it works with files system directly.
	/// There is no access to files system without extensions anymore.
	/// </summary>
	throw new Error('The method "sendFile" from Vault API is not supported');
};

Vault.prototype.sendFiles = function(serverUrl) {
	/// <summary>
	/// Send files from clientData to specified url.
	/// </summary>
	/// <param name="serverUrl" type="string"></param>
	/// <returns>bool</returns>
	return this.vault.sendFiles(serverUrl);
};

Vault.prototype.sendFilesAsync = function(serverUrl) {
	/// <summary>
	/// Send files from clientData to specified url in asynchronous mode
	/// </summary>
	/// <param name="serverUrl" type="string"></param>
	/// <returns>Promise object</returns>
	return this.vault.sendFilesAsync(serverUrl);
};

Vault.prototype.getResponse = function() {
	/// <summary>
	/// Returns the Response property, which is set with the server response data from the upload() method call.
	/// </summary>
	/// <returns>string</returns>
	return this.vault.getResponse();
};

Vault.prototype.getWorkingDir = function() {
	/// <summary>
	/// Get applet's current working directory (where files are to be downloaded into).
	/// Is not supported because it works with files system directly.
	/// </summary>
	throw new Error('The method "getWorkingDir" from Vault API is not supported');
};

Vault.prototype.getLastError = function() {
	/// <summary>
	/// Get the error message from the last operation.
	/// </summary>
	/// <returns>string</returns>
	return this.vault.getLastError();
};

Vault.prototype.clearClientData = function() {
	/// <summary>
	/// Clear all userdata values.
	/// </summary>
	return this.vault.clearClientData();
};

Vault.prototype.clearDownloadList = function() {
	/// <summary>
	/// Clears download file list.
	/// Is not supported.
	/// </summary>
	throw new Error('The method "clearDownloadList" from Vault API is not supported');
};

Vault.prototype.clearFileList = function() {
	/// <summary>
	/// Clears fileList.
	/// </summary>
	return this.vault.clearFileList();
};

Vault.prototype.setLocalFileName = function(filename) {
	/// <summary>
	/// Sets local file name.
	/// </summary>
	/// <param name="filename" type="string"></param>
	return this.vault.setLocalFileName(filename);
};

Vault.prototype.deleteFile = function() {
	/// <summary>
	/// Delete the file from the local file system specified by the argument,
	/// which is a fully qualified path to the file.
	/// Is not supported because it works with files system directly.
	/// </summary>
	throw new Error('The method "deleteFile" from Vault API is not supported');
};

Vault.prototype.downloadFileAndExecute = function() {
	/// <summary>
	/// Method that downloads file from web url, save it in users working directory and if
	/// user want opens it with appropriate program. If the same file already exists at the
	/// working directory, file not downloading anew.
	/// Is not supported because it works with files system directly.
	/// </summary>
	throw new Error('The method "downloadFileAndExecute" from Vault API is not supported');
};

Vault.prototype.downloadFile = function(strUrl) {
	/// <summary>
	/// Download file from fileUrl to working directory with specified credentials and post data.
	/// To use this method call <see cref="M:SetLocalFileName"/>.
	/// </summary>
	/// <param name="strUrl" type="string">Url to download file from.</param>
	/// <returns>bool, true if file downloaded successfully, false otherwise.</returns>
	return this.vault.downloadFile(strUrl);
};

Vault.prototype.downloadFiles = function() {
	/// <summary>
	/// Download files from downloadFileList to working directory with specified credentials and post data.
	/// To use this method call <see cref="M:addFileToDownloadList"/>.
	/// Multiple files downloading is not supported. Use <see cref="M:downloadFile"/> instead.
	/// </summary>
	throw new Error('The method "downloadFiles" from Vault API is not supported');
};

Vault.prototype.fileCreate = function() {
	/// <summary>
	///  Creates or overwrites the specified file.
	/// Is not supported because it works directly with files system
	/// </summary>
	throw new Error('The method "fileCreate" from Vault API is not supported');
};

Vault.prototype.fileOpenAppend = function() {
	/// <summary>
	/// Opens file with access to append material to a file.
	/// Is not supported because it works directly with files system
	/// </summary>
	throw new Error('The method "fileOpenAppend" from Vault API is not supported');
};

Vault.prototype.fileOpenWrite = function() {
	/// <summary>
	/// Opens file with access to write material to a file.
	/// Is not supported because it works directly with files system
	/// </summary>
	throw new Error('The method "fileOpenWrite" from Vault API is not supported');
};

Vault.prototype.fileWriteLine = function() {
	/// <summary>
	/// Writes a string followed by a line terminator to the text stream.
	/// Is not supported because it works directly with files system
	/// </summary>
	throw new Error('The method "fileWriteLine" from Vault API is not supported');
};

Vault.prototype.fileClose = function() {
	/// <summary>
	/// Closes the readers and the writers and releases any system resources associated with the them.
	/// Is not supported because it works directly with files system
	/// </summary>
	throw new Error('The method "fileClose" from Vault API is not supported');
};

Vault.prototype.getFileSize = function(fileName) {
	/// <summary>
	///  Gets the size of the current file.
	/// </summary>
	/// <param name="fileName" type="string"></param>
	/// <returns></returns>
	return this.vault.getFileSize(fileName);
};

Vault.prototype.writeText = function() {
	/// <summary>
	/// If file exists, writes a string to the stream. Else creates files and writes text.
	/// Is not supported because it works directly with files system
	/// </summary>
	throw new Error('The method "writeText" from Vault API is not supported');
};

Vault.prototype.readText = function(path, encoding) {
	/// <summary>
	/// Reads the stream from the current position to the end of the stream.
	/// </summary>
	/// <param name="fname" type="string"></param>
	/// <param name="encoding" type="string">Parameter for System.Text.Encoding.GetEncoding method. "UTF-8" is default.</param>
	/// <returns>
	/// string. The rest of the stream as a string, from the current position to the end.
	/// If the current position is at the end of the stream, returns the empty string("").
	/// </returns>
	return this.vault.readText(path, encoding);
};

Vault.prototype.readBase64 = function(path, offset, count) {
	/// <summary>
	/// Reads the string of base64 encoding bytes from the offset position to the offset + count of the stream.
	/// </summary>
	/// <param name="offset" type="int">start position</param>
	/// <param name="count" type="int">count of bytes</param>
	/// <param name="fname" type="string">path</param>
	/// <returns>
	/// string. Specified count of base64 encoded bytes from specified offset
	/// </returns>
	return this.vault.readBase64(path, offset, count);
};

Vault.prototype.setFileFieldName = function() {
	/// <summary>
	/// Sets field name for file (send() method). Default value is <b>vault_file</b>
	/// Is not supported. Was used to set ID of a file that is sent through sendFile method
	/// </summary>
	throw new Error('The method "setFileFieldName" from Vault API is not supported');
};

Vault.prototype.getFileFieldName = function() {
	/// <summary>
	/// Gets current field name for file (send() method). Default value is <b>vault_file</b>
	/// Is not supported. Was used to get ID of a file that is sent through sendFile method
	/// </summary>
	throw new Error('The method "getFileFieldName" from Vault API is not supported');
};

Vault.prototype.urlEncode = function() {
	/// <summary>
	/// Encodes a URL string.
	/// Is not supported. Use native encodeURIComponent
	/// </summary>
	throw new Error('The method "urlEncode" from Vault API is not supported');
};

Vault.prototype.urlDecode = function() {
	/// <summary>
	/// Converts a string that has been encoded for transmission in a URL into a decoded string.
	/// Is not supported. Use native decodeURIComponent
	/// </summary>
	throw new Error('The method "urlDecode" from Vault API is not supported');
};

/*@cc_on
@if (@register_classes == 1)
Type.registerNamespace("Aras.Client.Controls.Public");
Aras.Client.Controls.Public.Vault = Vault;
Vault.registerClass("Aras.Client.Controls.Public.Vault");
@end
@*/

/** Aras\Client\Controls\Public\Utils.js **/
function Utils(isIE, utils, fakeMethodHandler) {
	/// <summary>
	/// "aras.utils" instance of the class can be used in custom JavaScript code.
	/// Provides a set of useful methods.
	/// </summary>

	this.utils = utils;
	this.isIE = isIE;
	this.systemInfo = (utils && utils.systemInfo) ? {currentTimeZoneName: this.utils.systemInfo.currentTimeZoneName} : {currentTimeZoneName: new UtilsTimezoneHelper().getTimezoneNameFromJs()};

	this.init = function Utils_init() {
		var doFakeUtils = false, fakeUtilsMethod;
		if (!this.utils) {
			doFakeUtils = true;
			this.utils = {};
			fakeUtilsMethod = function() {
				if (fakeMethodHandler) {
					fakeMethodHandler();
				}
			};
		}

		for (var funcName in this) {
			var obj = this[funcName];
			var firstChar = funcName.charAt(0);

			if (typeof(obj) == 'function' && !this.hasOwnProperty(funcName) && firstChar.toLowerCase() == firstChar) {
				var newFuncName = firstChar.toUpperCase() + funcName.slice(1);
				this[newFuncName] = obj;
				if (doFakeUtils) {
					this.utils[newFuncName] = this.utils[funcName] = fakeUtilsMethod;
				}
			}
		}

		if (doFakeUtils) {
			this.utils.createXmlHttpRequestManager = this.utils.CreateXmlHttpRequestManager = function() {
				return null;
			};

			this.utils.stopHookingMouseInputInScript = this.utils.StopHookingMouseInputInScript = function() {};
			this.utils.startHookingMouseInputInScript = this.utils.StartHookingMouseInputInScript = function() {};
			this.utils.isClipboardSupported = function() {
				//it's the only way to check whether a browser supports clipboard operations or not
				//for those browsers that do not support clipboard operations the queryCommandEnabled throws an exception
				try {
					document.queryCommandEnabled('copy');
					return true;
				} catch (e) {
					return false;
				}
			};
			this.utils.setClipboardData = function(dataType, value, aWindow) {
				aWindow = aWindow || window;
				if (dataType === 'Text') {
					var textArea = aWindow.document.createElement('textarea');
					aWindow.document.body.appendChild(textArea);
					textArea.style.position = 'absolute';
					textArea.style.left = '-9999px';
					textArea.value = value;
					aWindow.getSelection().removeAllRanges();
					textArea.select();
					aWindow.document.execCommand('copy');
					aWindow.getSelection().removeAllRanges();
					textArea.parentNode.removeChild(textArea);
				}
			};

			if (this.isIE) {
				this.utils.setClipboardData = function(dataType, value) {
					window.clipboardData.setData(dataType, value);
				};

				this.utils.getClipboardData = function(dataType) {
					return window.clipboardData.getData(dataType) || '';
				};
			}
		}
	};
}

// <editor-fold defaultstate="collapsed" desc="Common utils methods">

Utils.prototype.setClipboardData = function Utils_setClipboardData(dataType, value, aWindow) {
	/// <summary>
	/// Set content, thats stored in clipboard
	/// </summary>
	this.utils.setClipboardData(dataType, value, aWindow);
};

Utils.prototype.getClipboardData = function Utils_getClipboardData(dataType) {
	/// <summary>
	/// Returns html content, thats stored in clipboard
	/// </summary>
	/// <returns>object</returns>
	if (!dataType) {
		dataType = 'Text';
	}
	return this.utils.getClipboardData('Text');
};

Utils.prototype.isClipboardSupported = function Utils_isClipboardSupported() {
	/// <summary>
	/// Checks if clipboard operations are supported 
	/// </summary>
	return this.utils.isClipboardSupported();
};

Utils.prototype.printPreviewDocument = function() {
	/// <summary>
	/// Print preview of HTMLDocument.
	/// Is not supported.
	/// </summary>
	throw new Error('The method "printPreviewDocument" from Utils API is not supported');
};

Utils.prototype.isValueNumber = function() {
	/// <summary>
	/// If val string represents a number (decimal or double) in the specified locale then true is returned.
	/// Is not supported.
	/// </summary>
	throw new Error('The method "isValueNumber" from Utils API is not supported');
};

Utils.prototype.hideKeyboardInput = function() {
	/// <summary>
	/// Hides/Unhides the key's hit in the window.
	/// Is not supported.
	/// </summary>
	throw new Error('The method "hideKeyboardInput" from Utils API is not supported');
};

Utils.prototype.createXmlHttpRequestManager = function Utils_createXmlHttpRequestManager() {
	/// <summary>
	/// Creates instance of XmlHttpRequestManager
	/// </summary>
	/// <returns></returns>
	return new XmlHttpRequestManager(this.utils);
};

// </editor-fold>

// <editor-fold defaultstate="collapsed" desc="Only IE utils methods">

Utils.prototype.createShellDataObject = function() {
	/// <summary>
	/// For Internet Explorer only. Create ShellDataObject instance
	/// Is not supported.
	/// </summary>
	throw new Error('The method "createShellDataObject" from Utils API is not supported');
};

Utils.prototype.isWindowVisible = function() {
	/// <summary>
	/// For Internet Explorer only.
	/// Is to fix incorrect behavior of window.closed in IE.
	/// Is not supported.
	/// </summary>
	throw new Error('The method "isWindowVisible" from Utils API is not supported');
};

Utils.prototype.setBrowserWindowStyle = function() {
	/// <summary>
	/// For Internet Explorer only. Sets the style of the browser window.
	/// Is not supported.
	/// </summary>
	throw new Error('The method "setBrowserWindowStyle" from Utils API is not supported');
};

Utils.prototype.closeRootWindow = function() {
	/// <summary>
	/// Closes the root window of the childWindow
	/// Is not supported.
	/// </summary>
	throw new Error('The method "closeRootWindow" from Utils API is not supported');
};

Utils.prototype.stopHookingMouseInputInScript = function Utils_stopHookingMouseInputInScript(window, name) {
	/// <summary>
	/// Stops hooking the mouse hit in the window.
	/// </summary>
	/// <param name="window" type="object">DHTML window object</param>
	/// <param name="name" type="string">Name of the HTML object for which to stop hooking</param>
	if (this.isIE) {
		this.utils.stopHookingMouseInputInScript(window, name);
	}
};

Utils.prototype.startHookingMouseInputInScript = function Utils_startHookingMouseInputInScript(doHide, window, name, checkFunctionInScript) {
	/// <summary>
	/// Starts hooking the mouse hit in the window.
	/// </summary>
	/// <param name="doHide" type="bool">flag to hide/unhide</param>
	/// <param name="window" type="object">DHTML window object</param>
	/// <param name="name" type="string">Name of the HTML object for which to start hooking</param>
	/// <param name="checkFunctionInScript" type="object">Script function object</param>
	if (this.isIE) {
		this.utils.startHookingMouseInputInScript(doHide, window, name, checkFunctionInScript);
	}
};

Utils.prototype.toHideMouseInputInScript = function() {
	/// <summary>
	/// For Internet Explorer only. Hides/Unhides the mouse hit.
	/// Is not supported.
	/// </summary>
	throw new Error('The method "toHideMouseInputInScript" from Utils API is not supported');
};

Utils.prototype.createSplashScreen = function() {
	/// <summary>
	/// For Internet Explorer only. Creates new splashscreen and return reference to it.
	/// Is not supported.
	/// </summary>
	throw new Error('The method "createSplashScreen" from Utils API is not supported');
};

Utils.prototype.openIEWindowInNewProcess = function Utils_openIEWindowInNewProcess(sURL, sName, sFeatures, bReplace) {
	/// <summary>
	/// OpenIEWindowInNewProcess is the analogue of the window.open()
	/// </summary>
	/// <param name="sURL" type="string">String that specifies the URL of the document to display</param>
	/// <param name="sName" type="string">String that specifies the name of the window. String is ignored when used as TARGET</param>
	/// <param name="sFeatures" type="string">String that contains a list of items separated by commas. Each item consists of an option and a value, separated by an equals sign</param>
	/// <param name="bReplace" type="string">Ignorable, just to save window.open analogue</param>
	/// <returns>window</returns>
	return window.open(sURL, sName, sFeatures, bReplace);
};

// </editor-fold>
/*@cc_on
@if (@register_classes == 1)
Type.registerNamespace("Aras.Client.Controls.Public");
Aras.Client.Controls.Public.Utils = Utils;
Utils.registerClass("Aras.Client.Controls.Public.Utils");
@end
@*/
/** ControlWrapperFactory.js **/
function ControlWrapperFactory() {

	function fakeMethodHandler(currentAras) {
		var resourceKey;
		if (currentAras.Browser.isIe()) {
			resourceKey = 'aras_object.fake_native_control_method_is_used_warning_ie';
		} else if (currentAras.Browser.isFf()) {
			resourceKey = 'aras_object.fake_native_control_method_is_used_warning_ff';
		} else {
			//do not throw any exceptions to have possibility to use this fake method in different browsers
			//just use the warning of FireFox
			resourceKey = 'aras_object.fake_native_control_method_is_used_warning_ch';
		}
		currentAras.AlertError(currentAras.getResource('', resourceKey, currentAras.getInnovatorUrl()));
	}

	this.createVaultWrapper = function(currentAras, parentAras) {
		if (!parentAras) {
			parentAras = currentAras;
		}
		fileSystemAccess.init(parentAras);
		var res = new Vault(fileSystemAccess, function() {
			fakeMethodHandler(currentAras);
		});
		res.init();
		return res;
	};

	this.createUtilsWrapper = function(currentAras, parentAras) {
		if (!parentAras) {
			parentAras = currentAras;
		}
		var res = new Utils(parentAras.Browser.isIe(), false, function() {
			fakeMethodHandler(parentAras);
		});
		res.init();
		return res;
	};
}

var controlWrapperFactory = new ControlWrapperFactory();

/** UtilsTimezoneHelper.js **/
function UtilsTimezoneHelper() {
	var currentTimezoneOffset = new Date(2014, 0, 1).getTimezoneOffset();

	this.getTimezoneNameFromJs = function UtilsTimezoneHelperGetTimezoneNameFromJs() {
		//some value coming from LOCAL_MACHINE\Software\Microsoft\Windows NT\CurrentVersion\Time Zones
		var defaultMapping = {
			'-13:00': 'Dateline Standard Time',
			'-12:00': 'Dateline Standard Time',
			'-11:00': 'Samoa Standard Time',
			'-10:00': 'Hawaiian Standard Time',
			'-09:00': 'Alaskan Standard Time',
			'-08:00': 'Pacific Standard Time',
			'-07:00': 'US Mountain Standard Time',
			'-06:00': 'Canada Central Standard Time',
			'-05:00': 'Eastern Standard Time',
			'-04:30': 'Venezuela Standard Time',
			'-04:00': 'Atlantic Standard Time',
			'-03:30': 'Newfoundland Standard Time',
			'-03:00': 'SA Eastern Standard Time',
			'-02:00': 'Mid-Atlantic Standard Time',
			'-01:00': 'Azores Standard Time',
			'+00:00': 'GMT Standard Time',
			'+01:00': 'W. Europe Standard Time',
			'+02:00': 'E. Europe Standard Time',
			'+03:00': 'Russian Standard Time',
			'+03:30': 'Iran Standard Time',
			'+04:00': 'Arabian Standard Time',
			'+04:30': 'Afghanistan Standard Time',
			'+05:00': 'West Asia Standard Time',
			'+05:30': 'India Standard Time',
			'+05:45': 'Nepal Standard Time',
			'+06:00': 'Central Asia Standard Time',
			'+06:30': 'Myanmar Standard Time',
			'+07:00': 'North Asia Standard Time',
			'+08:00': 'China Standard Time',
			'+09:00': 'Tokyo Standard Time',
			'+09:30': 'Cen. Australia Standard Time',
			'+10:00': 'E. Australia Standard Time',
			'+11:00': 'Central Pacific Standard Time',
			'+12:00': 'New Zealand Standard Time',
			'+13:00': 'Tonga Standard Time',
			//IR-025787. It is necessary as there is a difference between Standard Time and Daylight Saving Time
			'+14:00': 'Tonga Standard Time'
		};

		var offset = currentTimezoneOffset;
		var h = (Math.abs(offset) - Math.abs(offset) % 60) / 60;
		var m = Math.abs(offset) - h * 60;
		var key = (offset <= 0 ? '+' : '-') +
					(h < 10 ? '0' : '') + h + ':' +
						(m < 10 ? '0' : '') + m;
		key = defaultMapping[key];
		return key || 'UTC';
	};

	/*	this.test = function() {
			var fireTest = function (offset, expectedRes) {
				currentTimezoneOffset = offset;
				var res = this.getTimezoneNameFromJs();
				if (res !== expectedRes) {
					alert(res + " !== " + expectedRes);
				}
			}.bind(this);
			fireTest(12 * 60, "Dateline Standard Time");
			fireTest(12 * 60 - 20, "UTC");
			fireTest(5 * 60, "Eastern Standard Time");
			fireTest(15, "UTC");
			fireTest(0, "UTC");
			fireTest(-15, "UTC");
			fireTest(-3 * 60, "Russian Standard Time");
			fireTest(-5 * 60 - 30, "India Standard Time");
			fireTest(-5 * 60 - 45.5, "UTC");
			alert("passed");
		}; */
}

/** CriteriaConverter.js **/
function CriteriaConverter(clientUrl, arasObject) {
	this.ClientUrl = clientUrl + '/ClientHelper.asmx/Convert';
	this._aras = arasObject;
}

CriteriaConverter.prototype = {

	SimpleToAml: function CriteriaConverter$SimpleToAml(criteria, nodeName) {
		var modeName = 'SimpleToAml';
		var obj = {
			argsCollection: [
			{__type: 'NameValue', Name: 'action', Value: 'SimpleToAml'},
			{__type: 'NameValue', Name: 'criteria', Value: criteria},
			{__type: 'NameValue', Name: 'nodeName', Value: nodeName}]
		};
		return this._getCriteriaResponse(obj, modeName);
	},
	AdvancedToAml: function CriteriaConverter$AdvancedToAml(criteria, operation, nodeName) {
		var modeName = 'AdvancedToAml';
		var obj = {
			argsCollection: [
			{__type: 'NameValue', Name: 'action', Value: 'AdvancedToAml'},
			{__type: 'NameValue', Name: 'criteria', Value: criteria},
			{__type: 'NameValue', Name: 'nodeName', Value: nodeName},
			{__type: 'NameValue', Name: 'operation', Value: operation}]
		};
		return this._getCriteriaResponse(obj, modeName);
	},
	AmlToSimple: function CriteriaConverter$AmlToSimple(data) {
		return this._amlToMode('AmlToSimple', data);
	},
	AmlToAdvanced: function CriteriaConverter$AmlToAdvanced(data) {
		return this._amlToMode('AmlToAdvanced', data);
	},
	ClientUrl: '',
	_soapSend: function CriteriaConverter$SoapSend(methodName, content) {

		var xmlhttp = new XMLHttpRequest();
		xmlhttp.open('POST', this.ClientUrl + '?rnd=' + Math.random(), false);
		xmlhttp.setRequestHeader('Content-Type', 'application/json; charset=utf-8');
		xmlhttp.send(content);

		var responseText = xmlhttp.responseText;
		var evalMethod = window.eval;
		result = evalMethod('(' + responseText + ')');

		if (typeof result.d === 'undefined') {
			throw result.Message || 'Bad CriteriaConverter result.';
		} else {
			return result.d;
		}
	},
	_amlToMode: function CriteriaConverter$AmlToMode(modeName, data) {
		var obj = {
			argsCollection: [
			{__type: 'NameValue', Name: 'action', Value: modeName},
			{__type: 'NameValue', Name: 'data', Value: data}]
		};

		// check if we can minimize aml
		var objKey = data;
		if (data.indexOf('></Item>') > 0) {
			objKey = data.replace('></Item>', '/>');
		}
		return this._getCriteriaResponse(obj, modeName, objKey);
	},
	_getCriteriaResponse: function(obj, modeName, objKey) {
		var objJson = JSON.stringify(obj);
		var key = objKey || objJson;
		var response = this._findCriteriaResponseInCache(modeName, key);
		if (response === undefined) {
			response = this._soapSend(modeName, objJson);
			this._setCriteriaResponseIntoCache(modeName, key, response);
		}
		return response;
	},

	_findCriteriaResponseInCache: function(modeName, key) {
		if (!this._aras.commonProperties.criteriaConverterCache[modeName]) {
			this._aras.commonProperties.criteriaConverterCache[modeName] = this._aras.newArray();
			return;
		}

		var responseInCache = this._aras.commonProperties.criteriaConverterCache[modeName].filter(function(obj) {
			return obj.key === key;
		});
		if (responseInCache.length === 1) {
			return responseInCache[0].value;
		}
	},

	_setCriteriaResponseIntoCache: function(modeName, key, response) {
		var maxCacheResponseCount = 100;
		var cacheObject = this._aras.newObject();
		cacheObject.key = key;
		cacheObject.value = response;
		var currentCachedResponseCount = this._aras.commonProperties.criteriaConverterCache[modeName].length;
		if (currentCachedResponseCount > maxCacheResponseCount) {
			// we limit the size of the cache by maxCacheResponseCount
			this._aras.commonProperties.criteriaConverterCache[modeName].shift();
		}
		this._aras.commonProperties.criteriaConverterCache[modeName].push(cacheObject);
	}
};

/** ClientUrlsUtility.js **/
function ClientUrlsUtility(baseUrl) {
	if (!baseUrl) {
		throw new Error('Parameter baseUrl must be defined and be not empty.');
	}

	//(?:pattern) is a non-capturing match
	//the task is to capture path to Client folder and also capture "salt=..." if it is present
	var rex = new RegExp('(.*/Client)(?:/X-(salt=[^\\/]*)-X)?(?:\/|$)', 'i');
	var reResults = rex.exec(baseUrl);
	this._baseUrlWithoutSalt = reResults[1];
	this._salt = '';
	if (reResults[2]) {
		this._salt = reResults[2];
	}
}

ClientUrlsUtility.prototype.getBaseUrlWithoutSalt = function ClientUrlsUtilityGetBaseUrlWithoutSalt() {
	return this._baseUrlWithoutSalt;
};

ClientUrlsUtility.prototype.getSalt = function ClientUrlsUtilityGetSalt() {
	return this._salt;
};

/** aras_object.js **/
// (c) Copyright by Aras Corporation, 2004-2013.

/*
*   Aras Object used to expose the Client Side API for the Innovator Server.
*
*/

/*
global Aras variables: to (set/get) these variables use aras.(set/get)Variable
TearOff
DEBUG
*/

var system_progressbar1_gif = '../images/Progress.gif';

/**
 * Constructor for the Aras object.
 * @constructor
 * @param {Aras} parent
 */
function Aras(parent) {
	if (parent) {
		this.parentArasObj = parent;
		for (var prop in parent) {
			if (prop != 'privateProperties' && prop != 'parentArasObj' && prop != 'modalDialogHelper' && prop != 'shortcutsHelperFactory' && prop != 'CriteriaConverter' && !Aras.prototype[prop]) {
				this[prop] = parent[prop];
			}
		}
		this.IomInnovator = this.newIOMInnovator();
		this.vault = controlWrapperFactory.createVaultWrapper(this, parent);
		this.utils = controlWrapperFactory.createUtilsWrapper(this, parent);
	} else {
		var innovatorWindow = window; // !!! wrong, but temporary work
		this.Enums = Enums;
		this.commonProperties = new ArasCommonProperties();
		const baseTags = document.getElementsByTagName('base');
		let url = window.location.href;
		if (baseTags.length) {
			url = baseTags[0].href;
		}
		this.SetupURLs(url);
		this.varsStorage = null;
		this.vault = null;
		this.itemsCache = new ClientCache(this);
		this.windowsByName = [];
		this.preferenceCategoryGuid = 'B0D45DA3B9CE4196A9FEB1D7AD3E4870';
		this.mainWindowName = innovatorWindow.name;
		if (!this.mainWindowName) {
			var d = new Date();
			innovatorWindow.name = 'innovator_' + d.getHours() + 'h' + d.getMinutes() + 'm' + d.getSeconds() + 's';
			this.mainWindowName = innovatorWindow.name;
		}
		this.maxNestedLevel = 3; //constant to prevent recurrsion of nested forms (zero based)
		this.newFieldIndex = 0; //variable used in formtool to generate new field name
		this.sGridsSetups = {};
		this.rels2gridXSL = {};
		this.clipboard = new Clipboard(this);
		this.VaultServerURLCache = {};
		this.translationXMLNsURI = 'http://www.aras.com/I18N';
		this.translationXMLNdPrefix = 'i18n';

		this.IomFactory = null;
		this.IomInnovator = null;
		this.MetadataCache = null;
		this.metadataCacheCategotries = {};
		this.metadataCacheCategotries.variables = '824E7AB9B52446e58E05FC47A7507B21';
		this.user = ArasCore.user;
		this.OAuthServerDiscovery = OAuthServerDiscovery;
		this.OAuthClient = OAuthClient;
		this.tabsTitles = {};
	}

	this.modalDialogHelper = new ModalDialogHelper(this.getScriptsURL());
	this.privateProperties = new ArasPrivateProperties(this);
	this.controlsFactoryHelper = new ClientControlsFactoryHelper();
	this.shortcutsHelperFactory = new ShortcutsHelperFactory();

	var critConverter;
	var self = this;
	Object.defineProperty(this, 'CriteriaConverter', {
		get: function() {
			if (!critConverter) {
				var clientUrl = (new ClientUrlsUtility(self.commonProperties.BaseURL)).getBaseUrlWithoutSalt();
				critConverter = new CriteriaConverter(clientUrl, self);
			}
			return critConverter;
		}
	});
}

/**
 * Object to store common for all Aras objects properties
 * @constructor
 */
function ArasCommonProperties() {
	this.formsCacheById = {};
	this.userDom = Aras.prototype.createXMLDocument();
	this.userDom.loadXML('<Empty/>');
	this.userID = '';
	this.loginName = '';
	this.password = '';
	this.database = '';
	this.identityList = '';
	this.scriptsURL = '';
	this.baseURL = '';
	this.serverBaseURL = '';
	this.oauthServerUrl = '';
	this.user_type = '';
	this.idsBeingProcessed = {};
	this.clientRevision = '';
	this.IsSSVCLicenseOk = false;
	this.userReportServiceBaseUrl = '';
	this.cmfCopyBuffer = null;
	this.validateXmlCache = [];
	this.criteriaConverterCache = {};
}

/**
 * Object to store private properties of each of Aras objects
 * @constructor
 * @param {Aras} owner
 */
function ArasPrivateProperties(owner) {
	this.soap = new SOAP(owner);
}

Aras.prototype.showColorDialog = function Aras_showColorDialog(oldColor) {
	var reg = new RegExp('^#?(([a-fA-F0-9]){3}){1,2}$');
	if (!reg.test(oldColor)) {
		oldColor = '#ffffff';
	}
	//summary: show ColorDalog.html as modal window and allows to choose the color
	var options = {
		dialogHeight: 212,
		dialogWidth: 560,
		oldColor: oldColor, aras: this,
		content: 'colorDialog.html'
	};

	return window.ArasModules.Dialog.show('iframe', options).promise;
};

Aras.prototype.getOpenedWindowsCount = function Aras_GetOpenedWindowsCount(closeAllDuringLooping) {
	var winCount = 0;
	for (var wn in this.windowsByName) {
		var wnd = this.windowsByName[wn];
		if (typeof wnd == 'function') {
			continue;
		}

		if (this.isWindowClosed(wnd)) {
			this.deletePropertyFromObject(this.windowsByName, wn);
		} else {
			winCount++;
			if (closeAllDuringLooping) {
				wnd.logout_confirmed = true;
				wnd.close();
			}
		}
	}
	return winCount;
};

Aras.prototype.getCommonPropertyValue = function Aras_getCommonPropertyValue(propertyName, propertyDescription) {
	return this.CommonPropertyValue('get', propertyName, propertyDescription);
};

Aras.prototype.setCommonPropertyValue = function Aras_setCommonPropertyValue(propertyName, propertyValue, propertyDescription) {
	return this.CommonPropertyValue('set', propertyName, propertyValue, propertyDescription);
};

Aras.prototype.CommonPropertyValue = function Aras_CommonPropertyValue(action, propertyName, propertyValue, propertyDescription) {
	var res;
	if (action == 'get') {
		res = this.commonProperties[propertyName];
	} else {
		this.commonProperties[propertyName] = propertyValue;
	}

	return res;
};

/**
 * Adds id to a list of ids which are being processed in async operation.
 * Parameters are item id and operation description.
 * @param {string} id
 * @param {string} operationDescription
 */
Aras.prototype.addIdBeingProcessed = function Aras_addIdBeingProcessed(id, operationDescription) {
	this.commonProperties.idsBeingProcessed[id] = operationDescription;
};

/**
 * Removes id from a list of ids which are being processed in async operation.
 * @param {string} id
 */
Aras.prototype.removeIdBeingProcessed = function Aras_removeIdBeingProcessed(id) {
	this.deletePropertyFromObject(this.commonProperties.idsBeingProcessed, id);
};

/**
 * Checks if id is being processed in async operation.
 * @param {string} id
 * @returns {boolean}
 */
Aras.prototype.isIdBeingProcessed = function Aras_isIdBeingProcessed(id) {
	return (this.commonProperties.idsBeingProcessed[id] !== undefined);
};

/**
 * User item representing the user logged in is a special item
 * and thus is stored in the separate DOM.
 * @returns {boolean|Object}
 */
Aras.prototype.getLoggedUserItem = function Aras_getLoggedUserItem() {
	var item = this.commonProperties.userDom.selectSingleNode('Innovator/Item[@type=\'User\']');
	if (!item) {
		var res = this.getMainWindow().arasMainWindowInfo.getUserResult;
		if (res.getFaultCode() != 0) {
			if (this.DEBUG) {
				this.AlertError(this.getResource('', 'aras_object.fault_loading', typeName, res.getFaultCode()));
			}
			return false;
		}

		var newItem = res.results.selectSingleNode(this.XPathResult('/Item'));
		if (!newItem) {
			this.AlertError(this.getResource('', 'aras_object.user_not_found'));
		} else {
			this.commonProperties.userDom.loadXML('<Innovator>' + newItem.xml + '</Innovator>');
			item = this.commonProperties.userDom.selectSingleNode('Innovator/Item[@type=\'User\']');
		}
	}
	return item;
};

Aras.prototype.getIsAliasIdentityIDForLoggedUser = function Aras_getIsAliasIdentityIDForLoggedUser() {
	var identityID = '';
	var loggedUser = this.getLoggedUserItem();
	var identityNd = loggedUser.selectSingleNode('Relationships/Item[@type=\'Alias\']/related_id/Item[@type=\'Identity\']');
	if (identityNd) {
		identityID = identityNd.getAttribute('id');
	}

	return identityID;
};

Aras.prototype.getLoginName = function Aras_getLoginName() {
	return this.user.loginName;
};

Aras.prototype.getAuthenticationType = function Aras_getAuthenticationType() {
	return this.user.authenticationType;
};

Aras.prototype.isLocalAuthenticationType = function Aras_isLocalAuthenticationType() {
	return this.getAuthenticationType() === 'local';
};

/**
 * @returns {"admin"|"user"} return "admin" if logged user has Administrators or SuperUser Identity
 * otherwise return "user"
 */
Aras.prototype.getUserType = function Aras_getUserType() {
	return this.user.type;
};

Aras.prototype.isAdminUser = function Aras_isAdminUser() {
	return this.getUserType() === 'admin';
};

Aras.prototype.setUserType = function Aras_setUserType(usertype) {
	this.commonProperties.user_type = usertype;
};

Aras.prototype.setLoginName = function Aras_setLoginName(loginName) {
	this.commonProperties.loginName = loginName;
};

Aras.prototype.getUserReportServiceBaseUrl = function Aras_getUserReportServiceBaseUrl() {
	return this.commonProperties.userReportServiceBaseUrl;
};

Aras.prototype.setUserReportServiceBaseUrl = function Aras_setUserReportServiceBaseUrl(url) {
	this.commonProperties.userReportServiceBaseUrl = url;
};

Aras.prototype.SetupURLs = function Aras_SetupURLs(start_url) {
	var s = start_url.replace(/(^.+scripts\/)(.+)/i, '$1');
	this.commonProperties.scriptsURL = s;
	this.commonProperties.BaseURL = s.replace(/\/scripts\/$|\/reports\/$/i, '');
	this.commonProperties.serverBaseURL = this.commonProperties.BaseURL.replace(/\/client(\/.*)?$/i, '/Server/');
	this.commonProperties.innovatorBaseURL = this.commonProperties.serverBaseURL.replace(/\/Server\/$/i, '/');
	this.scriptsURL = this.commonProperties.scriptsURL;
};

Aras.prototype.getServerBaseURL = function Aras_getServerBaseURL() {
	return this.commonProperties.serverBaseURL;
};

Aras.prototype.getScriptsURL = function Aras_getScriptsURL(additionalPath) {
	var res = this._pathCombine(this.commonProperties.scriptsURL, additionalPath);
	return res;
};

Aras.prototype.getServerURL = function Aras_getServerURL() {
	var res = this.getCommonPropertyValue('serverBaseURL', 'Innovator server base URL') +
		'InnovatorServer.aspx';
	return res;
};

Aras.prototype.getBaseURL = function Aras_getBaseURL(additionalPath) {
	var res = this._pathCombine(this.commonProperties.BaseURL, additionalPath);
	return res;
};

Aras.prototype.getInnovatorUrl = function Aras_getInnovatorUrl() {
	return this.commonProperties.innovatorBaseURL;
};

Aras.prototype._pathCombine = function Aras_pathCombine() {
	if (!arguments || !arguments.length) {
		return;
	}
	if (arguments.length === 1 || arguments.length === 2 && arguments[1] === undefined) {
		return arguments[0]; //minor optimization
	}
	var curr, prev = arguments[0], res = [];
	if (prev) {
		res.push(prev);
	}
	for (var i = 1; i < arguments.length; i++) {
		prev = arguments[i - 1];
		curr = arguments[i];
		if (!prev || !curr) {
			continue;
		}
		if (prev.indexOf('/', prev.length - 1) > 0 && curr.substr(0, 1) === '/' ||
			prev.indexOf('\\', prev.length - 1) > 0 && curr.substr(0, 1) === '\\') {
			curr = curr.substr(1);
		}
		res.push(curr);
	}
	return res.join('');
};

/**
 * @param {string} resourceFileNm
 * @param {string} [parentUrl4XmlFolder]
 * @param {string} [resourceId]
 * @returns {string}
 */
Aras.prototype.getI18NXMLResource = function Aras_getI18NXMLResource(resourceFileNm, parentUrl4XmlFolder, resourceId) {
	if (!resourceFileNm) {
		return '';
	}
	if (!parentUrl4XmlFolder) {
		parentUrl4XmlFolder = this.getBaseURL();
	}
	if (parentUrl4XmlFolder.substr(parentUrl4XmlFolder.length - 1, 1) != '/') {
		parentUrl4XmlFolder += '/';
	}
	var Cache = this.getCacheObject();
	var langCd = this.getIomSessionContext().GetLanguageCode();
	var fullLocalizedUrl = parentUrl4XmlFolder + 'xml' + (langCd ? '.' + langCd : '') + '/' + resourceFileNm;
	var fullEnglishUrl = parentUrl4XmlFolder + 'xml' + '/' + resourceFileNm;
	if (resourceId === undefined) {
		resourceId = fullLocalizedUrl;
	}
	if (langCd == 'en') {
		return fullEnglishUrl;
	}
	if (Cache.XmlResourcesUrls[resourceId]) {
		return Cache.XmlResourcesUrls[resourceId];
	}

	var xmlhttp = new XMLHttpRequest();
	xmlhttp.open('HEAD', fullLocalizedUrl, false);
	xmlhttp.send('');
	if (xmlhttp.status == 404 || xmlhttp.statusText == 'Not Found') {
		Cache.XmlResourcesUrls[resourceId] = fullEnglishUrl;
	} else {
		Cache.XmlResourcesUrls[resourceId] = fullLocalizedUrl;
	}

	return Cache.XmlResourcesUrls[resourceId];
};

Aras.prototype.getTopHelpUrl = function Aras_getTopHelpUrl() {
	var topHelpVariable = this.getItemFromServerByName('Variable', 'TopHelpUrl', 'value');
	var topHelpUrl;
	if (topHelpVariable) {
		topHelpUrl = topHelpVariable.getProperty('value');
	}
	if (!topHelpUrl) {
		topHelpUrl = this.getBaseURL() + '/WebHelp/';
	}

	return topHelpUrl;
};

Aras.prototype.getUserID = function Aras_getUserID() {
	return this.user.id;
};

Aras.prototype.setUserID = function Aras_setUserID(userID) {
	this.commonProperties.userID = userID;
};

Aras.prototype.getDatabase = function Aras_getDatabase() {
	return this.user.database;
};

Aras.prototype.setDatabase = function Aras_setDatabase(database) {
	this.commonProperties.database = database;
};

Aras.prototype.getIdentityList = function Aras_getIdentityList() {
	return this.commonProperties.identityList;
};

Aras.prototype.setIdentityList = function Aras_setIdentityList(identityList) {
	this.commonProperties.identityList = identityList;
};

Aras.prototype.setVarsStorage = function Aras_setVarsStorage(varsStorage) {
	this.varsStorage = new VarsStorageClass();
};

Aras.prototype.getSelectCriteria = function Aras_getSelectCriteria(itemTypeId, isForRelationshipsGrid, xProperties) {
	if (!itemTypeId) {
		return '';
	}

	var currItemType = this.getItemTypeForClient(itemTypeId, 'id');
	if (!currItemType || currItemType.isError()) {
		return '';
	}

	currItemType = currItemType.node;
	var itTypeName = this.getItemProperty(currItemType, 'name');
	var isVersionable = (this.getItemProperty(currItemType, 'is_versionable') == '1');
	var isRelationshipType = (this.getItemProperty(currItemType, 'is_relationship') == '1');

	if (isForRelationshipsGrid == undefined) {
		isForRelationshipsGrid = false;
	}

	var key = this.MetadataCache.CreateCacheKey('getSelectCriteria', itemTypeId, isForRelationshipsGrid);
	if (xProperties) {
		const self = this;

		const flatXPropertyIdList = (function getFlatXPropertyIdList(xProps) {
			return Object.keys(xProps).reduce(function(result, key) {
				if (key !== 'related') {
					return result.concat(xProps[key].map(function(xProp) {
						return self.getItemProperty(xProp, 'id');
					}));
				} else {
					return result.concat(getFlatXPropertyIdList(xProps.related));
				}
			}, []);
		})(xProperties);

		if (flatXPropertyIdList.length > 0) {
			const xPropKey = ArasModules.cryptohash.MD5(flatXPropertyIdList.sort().join(','));
			key.push(xPropKey + '');
		}
	}
	if (isForRelationshipsGrid && isRelationshipType) {
		var relType = this.getRelationshipType(this.getRelationshipTypeId(itTypeName));
		if (relType && !relType.isError()) {
			var related_id = relType.getProperty('related_id');
			if (related_id) {
				key.push(related_id);
			}
		}
	}

	var cachedResult = this.MetadataCache.GetItem(key);
	if (!cachedResult) {
		var selectAttr = '';

		var visiblePropsItms = currItemType.selectNodes(this.getVisiblePropertiesXPath(itTypeName, isForRelationshipsGrid));
		for (var i = 0; i < visiblePropsItms.length; i++) {
			var propertyNd = visiblePropsItms[i];
			var propName = this.getItemProperty(propertyNd, 'name');
			if (selectAttr != '') {
				selectAttr += ',';
			}
			selectAttr += propName;
			if (this.getItemProperty(propertyNd, 'data_type') == 'foreign') {
				var dataSourceId = this.getItemProperty(propertyNd, 'data_source');
				var dataSourceItem = currItemType.selectSingleNode('Relationships/Item[@type="Property" and @id="' + dataSourceId + '"]');
				selectAttr += ',' + this.getItemProperty(dataSourceItem, 'name');
			}
		}

		if (selectAttr == '') {
			selectAttr = 'id';
		}

		selectAttr += ',created_by_id,created_on,modified_by_id,modified_on,locked_by_id,major_rev,css,current_state,keyed_name';

		if (isRelationshipType) {
			var relType = this.getRelationshipType(this.getRelationshipTypeId(itTypeName));
			if (relType && !relType.isError()) {
				var relatedTypeId = relType.getProperty('related_id');
				if (relatedTypeId) {
					selectAttr += ',related_id(' + this.getSelectCriteria(relatedTypeId, isForRelationshipsGrid, xProperties ? xProperties.related : null) + ')';
				}
			}
		}

		if (isVersionable) {
			selectAttr += ',new_version,generation,release_date,effective_date,is_current';
		}
		if (isRelationshipType) {
			selectAttr += ',source_id';
		}

		var hasThumbnail = currItemType.selectSingleNode('Relationships/Item[@type="Property"]/name[text()="thumbnail"]');
		if (hasThumbnail) {
			selectAttr += ',thumbnail';
		}

		if (xProperties) {
			xProperties[itemTypeId].forEach(function(xPropNode) {
				selectAttr += ',' + this.getItemProperty(xPropNode, 'name');
			}, this);
		}

		this.MetadataCache.SetItem(key, selectAttr);
		return selectAttr;
	} else {
		return cachedResult;
	}
};

Aras.prototype.getSearchMode = function Aras_getSearchMode(searchModeId) {
	return this.getSearchModes(searchModeId)[0];
};

/**
 * @param {string} searchModeId
 * @returns {Array} Array of all SearchMode items or with particular item if {searchModeId} was passed
 */
Aras.prototype.getSearchModes = function Aras_getSearchModes(searchModeId) {
	const searchModesResult = this.MetadataCache.GetSearchModes();

	if (searchModeId) {
		const foundNode = searchModesResult.selectSingleNode('Item[@id="' + searchModeId + '"]');
		return foundNode ? [foundNode] : [];
	}

	const itemNodesList = searchModesResult.selectNodes('Item');
	return Array.from(itemNodesList);
};

Aras.prototype.saveSavedSearches = function Aras_saveSavedSearches() {
	var specialID4SavedSearches_global = '56E808C94358462EAA90870A2B81AD96';
	var tmpArr = this.MetadataCache.GetItemsById(specialID4SavedSearches_global);
	var xml = '';
	for (var i = 0; i < tmpArr.length; i++) {
		var itm = tmpArr[i].content;
		if (itm && itm.getAttribute('action')) {
			itm.setAttribute('doGetItem', '0');
			xml += itm.xml;
		}
	}
	if (xml) {
		return this.soapSend('ApplyAML', '<AML>' + xml + '</AML>');
	}
};

Aras.prototype.getSavedSearches = function Aras_getSavedSearches(itemTypeName, location, autoSavedOnly, savedSearchId2Return) {
	var result = [];
	var specialID4SavedSearches_global = '56E808C94358462EAA90870A2B81AD96';
	var specialID4SavedSearches = this.getCommonPropertyValue('SavedSearchesSpecialID_' + itemTypeName);
	if (!specialID4SavedSearches) {
		specialID4SavedSearches = calcMD5('SavedSearchesSpecialID_' + itemTypeName).toUpperCase();
		this.setCommonPropertyValue('SavedSearchesSpecialID_' + itemTypeName, specialID4SavedSearches);
	}
	var tmpArr;
	if (savedSearchId2Return) {
		tmpArr = this.MetadataCache.GetItemsById(savedSearchId2Return);
	} else {
		tmpArr = this.MetadataCache.GetItemsById(specialID4SavedSearches);
	}
	if (tmpArr.length < 1) {
		var qry = this.newIOMItem('SavedSearch', 'get');
		if (savedSearchId2Return) {
			qry.setAttribute('id', savedSearchId2Return);
		} else {
			if (location !== 'ProjectTree') {
				qry.setProperty('itname', itemTypeName);
			} else {
				qry.setProperty('location', 'ProjectTree');
				qry.setAttribute('orderBy', 'label');
			}
		}
		qry.setProperty('owned_by_id', this.getIdentityList());
		qry.setPropertyCondition('owned_by_id', 'in');
		var res = qry.apply();
		if (res.isEmpty()) {
			var key = this.MetadataCache.CreateCacheKey('getSavedSearches', 'Just A Stub When No Saved Searches', specialID4SavedSearches, specialID4SavedSearches_global);
			var cacheCont = this.IomFactory.CreateCacheableContainer('', '');
			this.MetadataCache.SetItem(key, cacheCont);
			return result;
		}

		if (res.isError()) {
			this.AlertError(res);
			return result;
		}
		var allSearches = this.getSearchModes();
		var items = res.getItemsByXPath(this.XPathResult('/Item'));
		var itemsCount = items.getItemCount();
		for (var i = 0; i < itemsCount; i++) {
			var itm = items.getItemByIndex(i);
			var key = this.MetadataCache.CreateCacheKey('getSavedSearches', itm.getAttribute('id'), specialID4SavedSearches, specialID4SavedSearches_global);
			for (var j = 0; j < allSearches.length; j++) {
				key.push(allSearches[j].getAttribute('id'));
			}
			var cacheCont = this.IomFactory.CreateCacheableContainer(itm.node, itm.node);
			this.MetadataCache.SetItem(key, cacheCont);
		}
	}
	tmpArr = this.MetadataCache.GetItemsById(specialID4SavedSearches);
	for (var i = 0; i < tmpArr.length; i++) {
		var f1 = true;
		var f2 = true;
		var f3 = true;
		var f4 = true;
		var itm = tmpArr[i].content;
		if (itm) {
			if (itemTypeName && this.getItemProperty(itm, 'itname') != itemTypeName && itemTypeName !== 'ProjectTreeSalt_klj43') {
				f1 = false;
			}

			if (location && this.getItemProperty(itm, 'location') != location) {
				f2 = false;
			}
			if (autoSavedOnly && this.getItemProperty(itm, 'auto_saved') != '1') {
				f3 = false;
			}
			if (savedSearchId2Return && itm.getAttribute('id') != savedSearchId2Return) {
				f4 = false;
			}
			if (f1 && f2 && f3 && f4) {
				result.push(itm);
			}
		}
	}
	return result;
};

Aras.prototype.getVariable = function Aras_getVariable(varName) {
	try {
		if (!this.varsStorage) {
			return '';
		}

		return this.varsStorage.getVariable(varName);
	}
	catch (excep) {
		return '';
	}
};

Aras.prototype.resetUserPreferences = function Aras_resetUserPreferences() {
	this.MetadataCache.RemoveById(this.preferenceCategoryGuid);
	this.varsStorage = new VarsStorageClass();
};

Aras.prototype.setVariable = function Aras_setVariable(varName, varValue) {
	if (!this.varsStorage) {
		return 1;
	}

	try {
		if (this.getVariable(varName) != varValue) {
			var pp = this.varsStorage.setVariable(varName, varValue);

			params = {};
			params.varName = varName;
			params.varValue = varValue;
			this.fireEvent('VariableChanged', params);
		}
	}
	catch (excep) {
		return 2;
	}

	return 0;
};

Aras.prototype.removeVariable = function Aras_removeVariable(varName) {
	if (!this.varsStorage) {
		return 2;
	}

	return this.setVariable(varName, null);
};

/**
 * @param {string} nameForNewWindow
 * @param {string} [url] location of new document if window with nameForNewWindow hasn't defined. Created for IR-008617 "One Window (Main) Service report gives Access Denied"
 * @returns {Window}
 */
Aras.prototype.getActionTargetWindow = function Aras_getActionTargetWindow(nameForNewWindow, url) {
	var win = this.commonProperties.actionTargetWindow;

	if (win) {
		try {
			//IR-007415 "Status Bar/Indicator never ceases"
			//Check win.document to avoid access denied error
			if (!this.isWindowClosed(win) && win.document) {
				win = win;
			} else {
				win = null;
			}
		}
		catch (excep) {
			win = null;
		}
	}

	if (!win) {
		var width = 710; // This is a printable page width.
		var height = screen.availHeight / 2;
		var x = (screen.availHeight - height) / 2;
		var y = (screen.availWidth - width) / 2;
		var args = 'scrollbars=yes,resizable=yes,status,width=' + width + ',height=' + height + ',left=' + y + ',top=' + x;
		var loc = (url != undefined) ? url : this.getScriptsURL() + 'blank.html';
		win = window.open(loc, '', args);
		win.document.title = nameForNewWindow;

		this.setActionTargetWindow(win);
	}

	return win;
};

Aras.prototype.setActionTargetWindow = function Aras_setActionTargetWindow(win) {
	this.commonProperties.actionTargetWindow = win;
};

Aras.prototype._selectStatusBar = function Aras_selectStatusBar(status, statusbar) {
	try {
		if (!statusbar) {
			statusbar = (function() {
				const topWnd = this.getMostTopWindowWithAras(window);
				if (topWnd.statusbar) {
					return topWnd.statusbar;
				}

				if (topWnd.document.frames && topWnd.document.frames['statusbar']) {
					const statusbar = topWnd.document.frames['statusbar'];
					return statusbar;
				}
				const iframes = document.getElementsByTagName('iframe');
				let tmpFrames;
				for (let i = 0; i < iframes.length; i++) {
					tmpFrames = iframes[i] && iframes[i].contentWindow ? iframes[i].contentWindow.document.frames : null;
					if (tmpFrames && tmpFrames['statusbar']) {
						return tmpFrames['statusbar'];
					}
				}
			}.call(this));
		}

		if (statusbar) {
			if (statusbar.declaredClass === 'Aras.Client.Controls.Experimental.StatusBar') {
				return status && !!statusbar.listBar[status] ? statusbar : false;
			} else if (statusbar.declaredClass === 'Aras.Client.Frames.StatusBar') {
				return status && statusbar.containsStatusBarCell(status) ? statusbar : false;
			} else {
				return false;
			}
		}

		return false;
	}
	catch (excep) {
		return false;
	}
};

Aras.prototype.showStatusMessage = function Aras_showStatusMessage(id, text, imgURL, imgPosition) {
	const statusbar = this._selectStatusBar(id);
	if (statusbar) {
		return statusbar.setStatus(id, text, imgURL, imgPosition);
	}
	return false;
};

Aras.prototype.clearStatusMessage = function Aras_clearStatusMessage(messageID) {
	const statusbar = this._selectStatusBar(messageID);
	if (statusbar) {
		return statusbar.clearStatus(messageID);
	}
	return false;
};

Aras.prototype.setDefaultMessage = function Aras_setDefaultMessage(id, infoOrText, imgURL) {
	var info;
	if (imgURL != undefined) {
		info = {};
		info.text = infoOrText;
		info.imgURL = imgURL;
	} else {
		info = infoOrText;
	}

	const statusbar = this._selectStatusBar(id);
	if (this.getMostTopWindowWithAras(window).isTearOff && statusbar) {
		return statusbar.setDefaultMessage(id, info);
	}
	return false;
};

Aras.prototype.setStatus = function Aras_setStatus(text, image) {
	return this.showStatusMessage('status', text, image);
};

Aras.prototype.setStatusEx = function Aras_setStatusEx(text, id, image) {
	return this.showStatusMessage(id, text, image);
};

/**
 * Method to set the clear status bar value.
 */
Aras.prototype.clearStatus = function ArasObject_clearStatus(statID) {
	return this.clearStatusMessage(statID);
};

/**
 * Returns set of "header name" -> "header value" pairs. The headers are used to send request to server.
 * @param {string} [soapAction]
 * @returns {Object} set of "header name" -> "header value" pairs. The headers are used to send request to server.
 */
Aras.prototype.getHttpHeadersForSoapMessage = function Aras_getHttpHeadersForSoapMessage(soapAction) {
	const res = {};
	if (soapAction) {
		res['SOAPAction'] = soapAction;
	}

	//+++ setup HTTP_LOCALE and HTTP_TIMEZONE_NAME headers
	res['LOCALE'] = this.getCommonPropertyValue('systemInfo_CurrentLocale');
	res['TIMEZONE_NAME'] = this.getCommonPropertyValue('systemInfo_CurrentTimeZoneName');
	//--- setup HTTP_LOCALE and HTTP_TIMEZONE_NAME headers

	Object.assign(res, this.OAuthClient.getAuthorizationHeader());

	return res;
};

Aras.prototype.soapSend = function Aras_soapSend(methodName, xmlBody, url, saveChanges, soapController) {
	return this.privateProperties.soap.send(methodName, xmlBody, url, saveChanges, soapController);
};

/*
* For internal use only
*/
Aras.prototype.getEmptySoapResult = function Aras_getEmptySoapResult() {
	return new SOAPResults(this, '');
};

/**
 * Returns login name to communicate with Server (logged user login name)
 * @returns {string} login name of current user
 */
Aras.prototype.getCurrentLoginName = function Aras_getCurrentLoginName() {
	return this.getLoginName();
};

/**
 * Returns User id to communicate with Server (logged user id)
 * @returns {string} User ID
 */
Aras.prototype.getCurrentUserID = function Aras_getCurrentUserID() {
	return this.getUserID();
};

Aras.prototype.login = function Aras_login() {
	this.setVarsStorage();
	return this.user.login();
};

/**
 * Method to logoff the Innovator Server and close the session.
 */
Aras.prototype.logout = function() {
	this.setCommonPropertyValue('ignoreSessionTimeoutInSoapSend', true);

	if (this.getUserID()) {
		// Save in prefs the statistics about meta-data requested in this session
		// from the server. The statistics is used to preload meta-data in background.
		this.savePreferenceItems();
		this.saveSavedSearches();

		// send logoff message to primary and Notification servers
		this.soapSend('Logoff', '<logoff skip_unlock=\'0\'/>');
		if (this.UserNotification) {
			this.soapSend('Logoff', '', this.UserNotification.url);
		}

		this.commonProperties.userID = null;
		this.commonProperties.login;
		this.commonProperties.loginName = '';
		this.commonProperties.password = '';
		this.commonProperties.database = '';
		this.commonProperties.identityList = '';
	}
	this.setCommonPropertyValue('ignoreSessionTimeoutInSoapSend', undefined);
};

Aras.prototype.getVisiblePropertiesXPath = function Aras_getVisiblePropertiesXPath(itemTypeName, getForRelshipGrid) {
	var xpath;
	var isHidden = 'is_hidden' + (getForRelshipGrid ? '2' : '');
	if (this.isAdminUser() && itemTypeName == 'ItemType') {
		xpath = 'Relationships/Item[@type="Property" and (not(' + isHidden + ') or ' + isHidden + '="0" or name="label")]';
	} else {
		xpath = 'Relationships/Item[@type="Property" and (not(' + isHidden + ') or ' + isHidden + '="0")]';
	}

	return xpath;
};

Aras.prototype.XPathResult = function Aras_XPathResult(str) {
	var path = '//Result';
	if (str == undefined) {
		return (path);
	}
	if (!str) {
		return (path);
	}
	if (str == '') {
		return (path);
	}
	return (path + str);
};

Aras.prototype.XPathFault = function Aras_XPathResult(str) {
	var path = SoapConstants.EnvelopeBodyFaultXPath;
	if (str == undefined) {
		return (path);
	}
	if (!str) {
		return (path);
	}
	if (str == '') {
		return (path);
	}
	return (path + str);
};

Aras.prototype.XPathMessage = function Aras_XPathMessage(str) {
	var path = '//Message';
	if (str == undefined) {
		return (path);
	}
	if (!str) {
		return (path);
	}
	if (str == '') {
		return (path);
	}
	return (path + str);
};

/**
 * Check if xmldom (soap message) contains Message
 * @param {Object} xmlDom xml document with soap message
 */
Aras.prototype.hasMessage = function Aras_hasMessage(xmlDom) {
	return (xmlDom.selectSingleNode(this.XPathMessage()) != null);
};

/**
 * @param {Object} xmlDom xml document with soap message
 */
Aras.prototype.getMessageNode = function Aras_getMessageNode(xmlDom) {
	return xmlDom.selectSingleNode(this.XPathMessage());
};

/**
 * Method to generate a new ID by getting it from the server
 * @returns {string}
 */
Aras.prototype.generateNewGUID = function Aras_generateNewGUID() {
	return this.IomInnovator.getNewID();
};

/**
 * Method to test ID value to be temporary.
 *
 * @param {string} id ID to test.
 * @returns {boolean} is ID temporary.
 */
Aras.prototype.isTempID = function Aras_isTempID(id) {
	if (id.substring(0, 6) === 'ms__id') {
		return true;
	} else {
		var item = this.itemsCache.getItem(id);
		if (!item) {
			return false;
		}
		return (item.getAttribute('isTemp') === '1');
	}
};

/**
 * Method to transform a dom using the XSLT style sheet passed as string.
 */
Aras.prototype.applyXsltString = function(domObj, xslStr) {
	var xsl = this.createXMLDocument();
	xsl.loadXML(xslStr);
	return domObj.transformNode(xsl);
};

/**
 * Method to transform a dom using the XSLT style sheet passed as a URL.
 */
Aras.prototype.applyXsltFile = function(domObj, xslFile) {
	var xsl = this.createXMLDocument();
	var xmlhttp = this.XmlHttpRequestManager.CreateRequest();
	xmlhttp.open('GET', xslFile, false);
	xmlhttp.send(null);
	xsl.loadXML(xmlhttp.responseText);
	return domObj.transformNode(xsl);
};

/**
 * Method to evaluate the JavaScript code in the Aras object space.
 */
Aras.prototype.evalJavaScript = function Aras_evalJavaScript(jsCode) {
	eval('with(this){' + jsCode + '}');
};

/**
 * Method to print the frame
 * @param {Object} frame the frame object
 */
Aras.prototype.printFrame = function Aras_printFrame(frame) {
	frame.focus();
	frame.print();
};

/**
 * Method to evaluate JavaScript stored as a Method item on the client side.
 * @param {string|Object} methodNameOrNd the name or id of the Method item or Method Node
 * @param {Object} XMLinput inDom or XML string that is loaded into the _top.inDom
 * @param {Object} inArgs arguments for method(can not be changed the object in evalMethod)
 */
Aras.prototype.evalMethod = function Aras_evalMethod(methodNameOrNd, XMLinput, inArgs) {
	var isXmlNode = (typeof (XMLinput) === 'object') ? true : false;
	var methodNd, methodName;
	if (typeof (methodNameOrNd) === 'object') {
		methodName = this.getItemProperty(methodNameOrNd, 'name');
		methodNd = methodNameOrNd;
	} else {
		methodName = methodNameOrNd;
		var propNames;
		if (/^[0-9a-f]{32}$/i.test(methodName)) {
			propNames = ["id", "name"];
		} else {
			propNames = ["name", "id"];
		}
		for (var i in propNames) {
			methodNd = this.MetadataCache.GetClientMethodNd(methodName, propNames[i]);
			if (methodNd) {
				break;
			}
		}
	}

	if (!methodNd) {
		this.AlertError(this.getResource('', 'aras_object.error_in_evalmethod', methodName), '', '');
		return;
	}

	var methodCode = this.getItemProperty(methodNd, 'method_code');
	var methodNameUpper = methodName.toUpperCase();
	if ('ONCREATENEWPROJECT' === methodNameUpper) {
		var mixedFlag = '/* METHOD WAS MIXED DYNAMICALLY BY ARAS OBJECT */\n\n\n\n',
			oldSubString = 'var callbacks = {',
			newSubString = 'var callbacks = {\n' +
				'onload: function (dialog) {\n' +
				'	var windowToFocus = dialog.content.contentWindow;\n' +
				'	aras.browserHelper.setFocus(windowToFocus);\n' +
				'},';

		if (-1 === methodCode.indexOf(mixedFlag)) {
			methodCode = mixedFlag + methodCode.replace(oldSubString, newSubString);
			methodCode = mixedFlag + methodCode.replace(/\btop.aras\b/g, 'aras');
		}
	} else {
		var methodNamesWithTopAras = ['AFTERPROJECTUPDATECLIENT',
			'PM_CALL_SERVER_SIDE_SCHEDULE', 'PROJECT_CREATEPROJFROMTEMPLATE', 'PROJECT_CREATEPROJECTFROMPROJECT', 'PROJECT_CREATETEMPLATEFROMPROJ', 'PROJECT_CREATETEMPLATEFROMTEMPL',
			'PROJECT_SHOWGANTTCHART'];
		if (methodNamesWithTopAras.indexOf(methodNameUpper) !== -1) {
			methodCode = methodCode.replace(/\btop.aras\b/g, 'aras');
		}
	}

	var inDom;
	if (isXmlNode) {
		inDom = XMLinput.ownerDocument;
	} else {
		inDom = this.createXMLDocument();
		inDom.loadXML(XMLinput);
	}
	var self = this;

	function evalMethod_work() {
		var item = self.newIOMItem();
		var itemNode;

		item.dom = inDom;

		if (isXmlNode) {
			itemNode = XMLinput;
		} else {
			itemNode = item.dom.selectSingleNode('//Item');
		}

		if (itemNode) {
			item.node = itemNode;
		} else {
			item.node = undefined;
		}

		item.setThisMethodImplementation(new Function('inDom, inArgs', methodCode));

		return item.thisMethod(item.node, inArgs);
	}

	MethodCompatibilityMode(this.commonProperties.innovatorUpdateInfo.version, this.commonProperties.clientRevision, this);
	if (!this.DEBUG) {
		try {
			return (evalMethod_work());
		}
		catch (excep) {
			this.AlertError(this.getResource('', 'aras_object.method_failed', methodName), this.getResource('', 'aras_object.aras_object', excep.number, excep.description || excep.message), this.getResource('', 'common.client_side_err'));
			return;
		}
	} else {
		return (evalMethod_work());
	}
};

/**
 * AlertError
 * @param {string} errorMessage client-facing error message
 * @param {string} technicalErrorMessage the technical error message
 * @param {string} stackTrace the stack trace
 * @param {Object} options the object with settings
 */
Aras.prototype.AlertError = function Aras_AlertError(errorMessage, technicalErrorMessage, stackTrace, options) {
	var winOptions = (options && options.window) ? options.window : null;
	var win = this.getMostTopWindowWithAras(winOptions || window);

	if (errorMessage && typeof (errorMessage) !== 'string') {
		if (errorMessage.getFaultCode &&
			errorMessage.getFaultCode() === 'SOAP-ENV:Server.Authentication.SessionTimeout') {
			// To avoid multiple alerts with the same SessionTimeout error we just return resolved promise.
			// Dialog for handling this error will be shown from SOAP.handleSessionTimeout called by
			// sessionSoap module on SessionTimeout errors.
			return Promise.resolve();
		}
		if (SOAPResults.prototype.isPrototypeOf(errorMessage)) {
			return win.ArasModules.Dialog.alert('', {
				type: 'soap',
				data: errorMessage
			});
		} else if (errorMessage.isError) {
			return win.ArasModules.Dialog.alert('', {
				type: 'iom',
				data: errorMessage
			});
		}
	}

	if ((typeof (technicalErrorMessage) === 'string' && technicalErrorMessage.length > 0) || (typeof (stackTrace) === 'string' && stackTrace.length > 0)) {
		return win.ArasModules.Dialog.alert(errorMessage, {
			type: 'stack',
			technicalMessage: technicalErrorMessage,
			stackTrace: stackTrace
		});
	}

	return win.ArasModules.Dialog.alert(errorMessage, {
		type: 'error'
	});
};

Aras.prototype.AlertSuccess = function Aras_AlertSuccess(msg, argwin) {
	if (this.getPreferenceItemProperty('Core_GlobalLayout', null, 'core_successmessage_type') === 'Dialog') {
		ArasModules.Dialog.alert(msg, {
			type: 'success'
		});
	} else {
		var timeClose = parseInt(this.getPreferenceItemProperty('Core_GlobalLayout', null, 'core_popupmessage_timeout'));
		const notify = this.getNotifyByContext(window);
		notify(
			msg,
			{
				timeout: timeClose || 5000,
				type: 'success'
			}
		);
	}
};

Aras.prototype.AlertWarning = function Aras_AlertSuccess(msg) {
	ArasModules.Dialog.alert(msg, {
		type: 'warning'
	});
};

Aras.prototype.AlertAboutSession = function Aras_AlertAboutSession() {
	var formNd = this.getItemByName('Form', 'MySession', 0);
	if (formNd) {
		var width = this.getItemProperty(formNd, 'width') || 500;
		var height = this.getItemProperty(formNd, 'height') || 320;
		var param = {
			title: 'About My Session',
			formId: formNd.getAttribute('id'),
			aras: this,
			dialogWidth: width,
			dialogHeight: height,
			content: 'ShowFormAsADialog.html'

		};
		var win = this.getMostTopWindowWithAras(window);
		(win.main || win).ArasModules.Dialog.show('iframe', param);
	}
};

Aras.prototype.AlertAbout = function Aras_AlertAbout() {
	ArasCore.Dialogs.about();
};

Aras.prototype.AlertInternal_1 = function Aras_AlertInternal_1(argwin) {
	var win = window;
	if (argwin && !this.isWindowClosed(argwin)) {
		win = argwin;
	}

	var doc = null;
	try {
		doc = win.document;
	}
	catch (excep) {
	}

	var actEl = null;
	if (doc) {
		actEl = doc.activeElement;
	}

	if (actEl && actEl.tagName == 'FRAMESET') {
		var frms = doc.getElementsByTagName('FRAME');
		if (frms.length > 0) {
			actEl = frms[0];;
		}
	}

	try {
		if (actEl) {
			actEl.focus();
		}
	}

	catch (excep) {
	}
	try {
		win.focus();
	}
	catch (excep) {
	}

	return win;
};

/**
 * Displays a confirmation dialog box which contains a message and OK and Cancel buttons.
 * @param {string} message Message to display in a dialog.
 * @param {Window} ownerWindow parent window for the dialog.
 * @returns {boolean} true - if a user clicked the OK button. false - if a user clicked Cancel button.
 */
Aras.prototype.confirm = function Aras_confirm(message, ownerWindow) {

	if (window.showModalDialog) {
		var params = {
			buttons: {
				btnYes: this.getResource("", "common.ok"),
				btnCancel: this.getResource("", "common.cancel")
			},
			defaultButton: "btnCancel",
			aras: this,
			message: message
		};
		var res = this.modalDialogHelper.show("DefaultModal", ownerWindow || window, params, {
			dialogWidth: 300,
			dialogHeight: 200,
			center: true
		}, "groupChgsDialog.html");
		return res === "btnYes";
	} else {
		return window.confirm(message);
	}
};

Aras.prototype.prompt = function Aras_prompt(msg, defValue, argwin) {
	if (this.getCommonPropertyValue('exitWithoutSavingInProgress')) {
		return;
	}
	var win = this.AlertInternal_1(argwin);

	var htmlContent =
		'<head>' +
		'	<link rel="stylesheet" href="../styles/default.css">' +
		'	<style type="text/css">@import "../javascript/include.aspx?classes=common.css";</style>' +
		'</head>' +
		'<div id="dialogContent" style="margin: 0px; overflow: hidden; left:0px; top:0px; right:0px; bottom:0px; padding: 10px;">' +
			'<div style="position:relative; margin-bottom:10px; text-align:right;">' +
				'<span style="position: absolute; left:0px; font-size: 14px;" class="sys_f_label">Script Prompt:</span>' +
				'<input type="button" style="width: 100px; margin-right: 10px;" id="ok" class="btn" onclick="dialog.close(textInput.value);" value="' + this.getResource('', 'common.ok') + '"/>' +
			'</div>' +
			'<div style="position: relative; margin-bottom: 5px; text-align:right;">' +
				'<input type="button" style="width: 100px; margin-right: 10px;" id="cancel" class="btn cancel_button" onclick="dialog.close();" value="' + this.getResource('', 'common.cancel') + '"/>' +
			'</div>' +
			'<div style="position: relative; margin-bottom: 10px;">' +
				'<div id="msg" style="margin-bottom: 5px; font-size: 14px;" class="sys_f_label">' + msg + '</div>' +
				'<input style="position: relative; width:468px; " id="textInput" value=' + defValue + '>' +
			'</div>' +
		'</div>';

	var scriptContent =
		'<script>' +
		'var dialog = window.frameElement.dialogArguments.dialog;' +
		'onload = function onload_handler(){\n' +
		'	document.body.addEventListener("keydown", function(evt){\n' +
		'		var keyCode = evt.keyCode || evt.which;\n' +
		'		if(keyCode == 27){\n' +
		'			dialog.close();\n' +
		'			}\n' +
		'		});\n' +
		'	var textInput = document.getElementById(\'textInput\');\n' +
		'	if (textInput) {\n' +
		'		textInput.focus();\n' +
		'	}\n' +
		'	window.focus();\n' +
		'}\n' +
		'onunload = function onunload_handler(){\n' +
		'	if (window.returnValue==undefined) window.returnValue = null;' +
		'}\n' +
		'</script>';
	function writeContent(targetWindow) {
		var doc = targetWindow.document;
		doc.write(htmlContent);
		doc.write(scriptContent);
	}

	var params = {};
	params.writeContent = writeContent;
	params.aras = this;

	params.dialogWidth = 500;
	params.dialogHeight = 170;
	params.content = 'modalDialog.html';
	params.title = this.getResource('', 'aras_object.aras_user_prompt');

	return (win.main || win).ArasModules.Dialog.show('iframe', params).promise;
};

/**
 * Method to evaluate JavaScript stored as a Method item on the client side.
 * @param {string} methodName the name of the Method item
 * @param {Object} itemDom the item dom
 * @param {Object} [addArgs] Object with any additional parameters.
 */
Aras.prototype.evalItemMethod = function Aras_evalItemMethod(methodName, itemNode, addArgs) {
	var methodNd = this.MetadataCache.GetClientMethodNd(methodName, 'name');
	if (!methodNd) {
		this.AlertError(this.getResource('', 'aras_object.erroe_eval_item_method', methodName), '', '');
		return;
	}

	var methodCode = this.getItemProperty(methodNd, 'method_code'),
		methodNameUpper = methodName.toUpperCase();

	var methodNamesWithTopAras = ['AFTERPROJECTUPDATECLIENT',
		'PM_CALL_SERVER_SIDE_SCHEDULE', 'PROJECT_CREATEPROJFROMTEMPLATE', 'PROJECT_CREATEPROJECTFROMPROJECT', 'PROJECT_CREATETEMPLATEFROMPROJ', 'PROJECT_CREATETEMPLATEFROMTEMPL',
		'PROJECT_SHOWGANTTCHART', 'PROJECT_CFGSEARCHDIALOG4ASSGNMTS', 'PROJECTTIMEREPORT'];
	if (methodNamesWithTopAras.indexOf(methodNameUpper) !== -1) {
		methodCode = methodCode.replace(/\btop.aras\b/g, 'aras');
		var methodNamesWithTop = ['PROJECT_CFGSEARCHDIALOG4ASSGNMTS'];
		if (methodNamesWithTop.indexOf(methodNameUpper)) {
			methodCode = methodCode.replace(/\btop\b/g, 'aras.getMostTopWindowWithAras(window)');
		}
	}

	var self = this;

	function evalItemMethod_work() {
		var item = self.newIOMItem();
		if (itemNode) {
			item.dom = itemNode.ownerDocument;
			item.node = itemNode;
		}
		item.setThisMethodImplementation(new Function('inDom', 'inArgs', methodCode));

		return item.thisMethod(item.node, addArgs);
	}

	MethodCompatibilityMode(this.commonProperties.innovatorUpdateInfo.version, this.commonProperties.clientRevision, this);
	if (!this.DEBUG) {
		try {
			return (evalItemMethod_work());
		}
		catch (excep) {
			this.AlertError(this.getResource('', 'aras_object.method_failed', methodName), this.getResource('', 'aras_object.aras_object', excep.number, excep.description), this.getResource('', 'common.client_side_err'));
			return;
		}
	} else {
		return (evalItemMethod_work());
	}
};

/**
 * Method to invoke an Innovator Method on the server side.
 * @param {string} action the server action to be performed
 * @param {string} body the message body for the action
 */
Aras.prototype.applyMethod = function Aras_applyMethod(action, body) {
	var res = this.soapSend('ApplyMethod', '<Item type="Method" action="' + action + '">' + body + '</Item>');
	if (res.getFaultCode() != 0) {
		this.AlertError(res);
		return false;
	}
	return res.getResultsBody();
};

/**
 * Method to invoke an action on an item on the server side.
 * @param {string} action the the server action to be performed, which is the Innovator Method name
 * @param {string} type the ItemType name
 * @param {string} body the message body for the action
 */
Aras.prototype.applyItemMethod = function(action, type, body) {
	var res = this.soapSend('ApplyItem', '<Item type="' + type + '" action="' + action + '">' + body + '</Item>');

	if (res.getFaultCode() != 0) {
		this.AlertError(res);
		return false;
	}
	return res.getResultsBody();
};

/**
 * Method to apply an item on the server side.
 * @param {string} body the message body for the item
 */
Aras.prototype.applyAML = function(body) {
	var res = this.soapSend('ApplyAML', body);
	if (res.getFaultCode() != 0) {
		this.AlertError(res);
		return false;
	}
	return res.getResultsBody();
};

/**
 * Method to compile VB or C# code on the server side to check syntax.
 * @param body the method item xml
 */
Aras.prototype.compileMethod = function(body) {
	var res = this.soapSend('CompileMethod', body);
	if (res.getFaultCode() != 0) {
		this.AlertError(res);
		return '';
	}
	return res.getResultsBody();
};

/**
 * Method to apply an item on the server side.
 * @param body the message body for the item
 */
Aras.prototype.applyItem = function Aras_applyItem(body) {
	var res = this.soapSend('ApplyItem', body);
	if (res.getFaultCode() != 0) {
		this.AlertError(res);
		return '';
	}
	return res.getResultsBody();
};

Aras.prototype.canInvokeAction = function Aras_canInvokeActionImpl(actionId) {
	var canInvokeAction = true;
	if (actionId) {
		// Request to Server should be changed to request to Cache in further implementations.
		var action = this.newIOMItem('Action', 'get');
		action.setID(actionId);
		action.setAttribute('select', 'can_execute, location');
		action = action.apply();
		if (action.isError()) {
			this.AlertError(action);
			return false;
		}

		var canExecuteMethodName = action.getPropertyAttribute('can_execute', 'keyed_name');
		var location = action.getProperty('location');
		canInvokeAction = this.canInvokeActionImpl(canExecuteMethodName, location);
	}
	return canInvokeAction;
}

Aras.prototype.canInvokeActionImpl = function Aras_canInvokeActionImpl(methodName, location) {
	var canInvokeAction = true;
	if (methodName) {
		if (location === 'client') {
			// Result of 'this.evalMethod' can be value of any type (integer, string, boolean and etc.).
			// For compatibility with "location === 'server'" logic:
			// if value string 'true' or boolean true, canInvokeAction = true, in all other cases canInvokeAction = false
			var evalResult = this.evalMethod(methodName);
			//evalResult can be 'undefined'.
			if (!evalResult || evalResult.toString() != 'true') {
				canInvokeAction = false;
			}
		} else if (location === 'server') {
			var canInvoketem = this.newIOMItem('Action', methodName);
			canInvoketem = canInvoketem.apply();
			if (canInvoketem.isError() || canInvoketem.getResult() != 'true') {
				canInvokeAction = false;
			}
		}
	}

	return canInvokeAction;
};

/**
 * Invoke the Method associated with an action.
 * @param {string} action the the Action item
 * @param {string} itemTypeID
 * @param {string} thisSelectedItemID
 */
Aras.prototype.invokeAction = function Aras_invokeAction(action, itemTypeID, thisSelectedItemID) {
	with (this) {
		var self = this;
		var statusId = showStatusMessage('status', getResource('', 'aras_object.invoking_action'), system_progressbar1_gif);
		var name = getItemProperty(action, 'name');
		var actionType = getItemProperty(action, 'type');
		var target = getItemProperty(action, 'target');
		var location = getItemProperty(action, 'location');
		var body = getItemProperty(action, 'body');
		var onCompleteMethodName = this.getItemPropertyAttribute(action, 'on_complete', 'keyed_name');
		var itemTypeName = null;

		if (itemTypeID != undefined && itemTypeID) {
			itemTypeName = getItemTypeName(itemTypeID);
		}

		var methodName = this.getItemPropertyAttribute(action, 'method', 'keyed_name');
		var results;
		var selectedItem;

		if (actionType == 'item') {
			var item_query = getItemProperty(action, 'item_query');
			var xslt = '<xsl:stylesheet xmlns:xsl=\'http://www.w3.org/1999/XSL/Transform\' version=\'1.0\'>' +
				'<xsl:output method=\'xml\' omit-xml-declaration=\'yes\' standalone=\'yes\' indent=\'yes\'/>' +
				'<xsl:template match=\'/\'>' +
				'<xsl:apply-templates/></xsl:template>' +
				'<xsl:template match=\'Item\'>' + item_query + '</xsl:template>' +
				'</xsl:stylesheet>';
			var itemDom = createXMLDocument();
			var doApplyQuery = false;

			// IR-016631 "InvokeAction works wrong."
			selectedItem = itemsCache.getItemByXPath('//Item[@id=\'' + thisSelectedItemID + '\' and (@isDirty=\'1\' or @isTemp=\'1\')]');

			// if item isn't dirty and isn't temp
			if (!selectedItem) {
				// retrieve item from server
				selectedItem = getItemById(itemTypeName, thisSelectedItemID, 0);

				// seems, item was deleted
				if (!selectedItem) {
					AlertError(this.getResource('', 'aras_object.item_not_found', itemTypeName, thisSelectedItemID));
					return;
				}

				if (item_query != '') {
					itemDom.loadXML(selectedItem.xml);
					doApplyQuery = true;
				}
			}

			//request selectedItem from server via item_query transformation
			if (doApplyQuery) {
				// if item_query is invalid string(__is_new__ for example), then this request do not return anything and value from cache will be used.
				var query = applyXsltString(itemDom, xslt);
				if (query) {
					var result = this.soapSend('ApplyItem', query);
					//if nothing was received, then use item from cache or if it is not existed in cache use temp item.
					if (result.getFaultCode() != 0) {
						selectedItem = itemDom.documentElement;
					} else {
						var resultItem = result.getResult().selectSingleNode('Item');
						mergeItem(selectedItem, resultItem);
					}
				}
			}

			if (location == 'server') {
				var inDom = createXMLDocument();
				inDom.loadXML(selectedItem.xml);
				var inItem = inDom.selectSingleNode('//Item');
				inItem.setAttribute('action', methodName);
				var res = soapSend('ApplyItem', inItem.xml);
				if (res.getFaultCode() != 0) {
					this.AlertError(res);
					clearStatusMessage(statusId);
					return false;
				}
				results = res.getResultsBody();
			} else if (location == 'client') {
				var selectedItemXmlBeforeAction = selectedItem.xml;
				var itemWasChangedDurinAction = false;

				results = evalItemMethod(methodName, selectedItem, null);

				if (selectedItem) {
					itemWasChangedDurinAction = (selectedItemXmlBeforeAction !== selectedItem.xml);

					if (itemWasChangedDurinAction && this.isLocked(selectedItem)) {
						selectedItem.setAttribute('isDirty', '1');
						this.uiReShowItemEx(thisSelectedItemID, selectedItem);
					}
				}
			}

			if (onCompleteMethodName) {
				var methodArgs = {};
				methodArgs.results = results;
				results = evalItemMethod(onCompleteMethodName, selectedItem, methodArgs);
			}
		} else if (actionType == 'itemtype' || actionType == 'generic') {
			if (location == 'server') {
				if (body != '' && actionType == 'itemtype') {
					results = applyItemMethod(methodName, itemTypeName, body);
				} else if (body != '' && actionType == 'generic') {
					results = applyMethod(methodName, body);
				} else {
					if (body == '') {
						body = '<id>' + thisSelectedItemID + '</id>';
					}
					results = applyMethod(methodName, body);
				}
			} else if (location == 'client') {
				var methodNode = this.MetadataCache.GetClientMethodNd(methodName, 'name');
				results = evalMethod(methodName, body, methodNode);
				if (onCompleteMethodName) {
					var methodArgs = {};
					methodArgs.results = results;
					results = evalItemMethod(onCompleteMethodName, body, methodArgs);
				}
			}
		}

		var doc;

		if (location == 'server') {
			var subst = createXMLDocument();
			subst.loadXML(results);

			if (subst.documentElement) {
				var content = subst.documentElement.text;
			} else {
				var content = '';
			}
			subst = null;
		} else {
			var content = results;
		}

		var tabsObj = this.getMainWindow().arasTabs;
		var close = 'var close = function(callback) { \
					if (!callback) { \
						tabsObj.removeTab(this.frameElement.id); \
					} else { \
						callback(true); \
					} \
				};';

		var focus = 'var focus = function() { \
						tabsObj.selectTab(this.frameElement.id); \
					};';

		var createScript = function(win) {
			var script = win.document.createElement('script');
			script.textContent = 'var tabsObj = window.parent.arasTabs;';
			script.textContent += close;
			script.textContent += focus;
			win.document.body.appendChild(script);
		};

		var openContentInTab = function(mode) {
			var winName = self.mainWindowName + '_' + self.getItemProperty(action, 'id');
			var win;
			mode = mode || 'window';

			if (mode === 'window') {
				winName = winName + '_' + Date.now();
			}

			var mainWindowDoc = self.getMainWindow().document;
			var frame = mainWindowDoc.getElementById(winName);

			if (!frame) {
				win = tabsObj.open(aras.getScriptsURL() + 'blank.html', winName);
				tabsObj.updateTitleTab(winName, {label: name, image: '../images/TabDefault.svg'});

			} else {
				win = frame.contentWindow;
				win.focus();
			}

			// if content is very large doc.write(content) falls with errors(out of memory, example)
			// so write content by parts
			var contentLength = 250000;
			var cycles = Math.ceil(content.length / contentLength);
			for (var i = 0; i < cycles; i++) {
				win.document.write(content.substring(i * contentLength, (i + 1) * contentLength));
			}
			win.document.write('<br />');
			win.document.body.style.background = '#fff';

			if (!win.tabsObj) {
				createScript(win);
			}
		};

		switch (target) {
			case 'window':
				if (tabsObj) {
					openContentInTab('window');
					break;
				}

				var width = 710; // This is a printable page width.
				var height = screen.height / 2;
				var x = (screen.height - height) / 2;
				var y = (screen.width - width) / 2;
				var args = 'scrollbars=yes,resizable=yes,status,width=' + width + ',height=' + height + ',left=' + y + ',top=' + x;
				var win = open('', '', args);
				win.focus();
				doc = win.document.open();
				doc.write(content);
				doc.close();
				doc.title = name;
				break;
			case 'main':
				var mainWindow = getMainWindow();
				// Chrome does not cleans the window object on document.write
				// differently from other browsers. Proof:
				// https://stackoverflow.com/questions/12417121/document-open-document-write-not-properly-clearing-the-document-in-chrome-i
				if (Browser.isCh()) {
					if (mainWindow.work.onbeforeunload){
						mainWindow.work.onbeforeunload();
					}
					makeItemsGridBlank(false);
				}
				// Replacing window location does not finish work before writing in document when move main menu to the grid`s area.
				setTimeout(function() {
					doc = mainWindow.work.document.open();
					doc.write(content);
					doc.close();
				}, 0);
				break;
			case 'none':
				break;
			case 'one window':
				if (tabsObj) {
					openContentInTab('one window');
					break;
				}

				var targetWindow = getActionTargetWindow(name);
				doc = targetWindow.document;
				// if content is very large doc.write(content) falls with errors(out of memory, example)
				// so write content by parts
				var contentLength = 250000;
				var cycles = Math.ceil(content.length / contentLength);
				for (var i = 0; i < cycles; i++) {
					doc.write(content.substring(i * contentLength, (i + 1) * contentLength));
				}
				doc.write('<br />');
				break;
		}
		clearStatusMessage(statusId);
	}
};

Aras.prototype.runReport = function Aras_runReport(report, itemTypeID, item) {
	if (!report) {
		this.AlertError(this.getResource('', 'aras_object.failed_get_report'), '', '');
		return;
	}

	var report_location = this.getItemProperty(report, 'location');
	var self = this;
	var results;

	if (report_location == "client") {
		var result = this.runClientReport(report, itemTypeID, item);
		if (result.then) {
			result.then(processResults);
		} else {
			processResults(result);
		}
	}
	else if (report_location == "server") {
		results = this.runServerReport(report, itemTypeID, item);
		var tmpDom = this.createXMLDocument();
		if (results) {
			tmpDom.loadXML(results);
			results = tmpDom.documentElement.text;
		}
		processResults(results);
	}
	else if (report_location == "service") {
		var url = this.getServerBaseURL() + "RSGateway.aspx?irs:Report=" + this.getItemProperty(report, "name");
		var report_query = this.getItemProperty(report, "report_query");
		if (report_query) {
			var xslt = '' +
			'<?xml version=\'1.0\' encoding=\'utf-8\'?>' +
			'<xsl:stylesheet xmlns:xsl=\'http://www.w3.org/1999/XSL/Transform\' version=\'1.0\'>' +
			'	<xsl:output method=\'xml\' omit-xml-declaration=\'yes\' standalone=\'yes\' indent=\'yes\'/>' +
			'	<xsl:template match=\'/\'><xsl:apply-templates/></xsl:template>' +
			'	<xsl:template match=\'Item\'><result>' + report_query + '</result></xsl:template>' +
			'</xsl:stylesheet>';
			var itemDom = this.createXMLDocument();
			if (item) {
				itemDom.loadXML(item.xml);
			} else {
				var typeName;
				if (itemTypeID) {
					typeName = this.getItemTypeName(itemTypeID);
					itemDom.loadXML('<Item type=\'' + typeName + '\' id=\'\'/>');
					item = true;
				}

			}

			var qryString = report_query;
			if (item) {
				qryString = this.applyXsltString(itemDom, xslt);
				if (qryString) {
					tmpDom = this.createXMLDocument();
					tmpDom.loadXML(qryString);
					qryString = tmpDom.documentElement.text;
				}
			}
			if (qryString) {
				url += '&' + qryString;
			}
		}
		processResults(results);
	}

	function processResults (results) {
		if (typeof (results) === "undefined") {
			results = "";
		}
		else if (typeof (results) !== "string") {
			results = results.toString();
		}
		// Transformation for vault-images
		var substr = "vault:\/\/\/\?fileid\=";
		var fileIdpos = results.toLowerCase().indexOf(substr);
		while (fileIdpos != -1) {
			var vaultUrl = results.substring(fileIdpos, fileIdpos + substr.length + 32);
			fileIdpos += substr.length;
			var fileId = vaultUrl.replace(/vault:\/\/\/\?fileid\=/i, "");
			var vaultUrlwithToken = self.IomInnovator.getFileUrl(fileId, self.Enums.UrlType.SecurityToken);
			results = results.replace(vaultUrl, vaultUrlwithToken);
			var fileIdpos = results.toLowerCase().indexOf(substr, fileIdpos + 32);
		}

		// Add element <base> in result for correct loading picture.
		function isBaseTagInHead(results) {
			const head = results.match(/<head[^]*?>[^]*?<\/head>/i);
			if (head) {
				const searchBaseTagRegExp = /<head[^]*?>[^]*?<base[^]*?>[^]*?<\/head>/i;
				return searchBaseTagRegExp.test(head[0]);
			}
		}
		if (!isBaseTagInHead(results)) {
			var base = "<base href=\"" + self.getScriptsURL() + "\"></base>";
			results = results.replace(/<(head[^]*?)\/>/i, "<$1></head>");
			results = results.replace(/(<head[^]*?>)([^]*?<\/head>)/i, "$1" + base + "$2");
			if (!isBaseTagInHead(results)) {
				results = results.replace(/<html[^]*?>/i, "$0" + "<head>" + base + "</head>");
			}
		}
		//Chrome new window blocked non event user action
		setTimeout(function() {
			self.targetReport(report, report_location, url, results);
		}, 0)
	}
}

Aras.prototype.targetReport = function(report, report_location, url, results, doReturnWindow) {
	var target = this.getItemProperty(report, 'target') || 'window';
	var doc = null;
	var self = this;
	var tabsObj = this.getMainWindow().arasTabs;

	var close = 'var close = function(callback) { \
					if (!callback) { \
						tabsObj.removeTab(this.frameElement.id); \
					} else { \
						callback(true); \
					} \
				};';

	var focus = 'var focus = function() { \
					tabsObj.selectTab(this.frameElement.id); \
				};';

	var createScript = function(win) {
		var script = win.document.createElement('script');
		script.textContent = 'var tabsObj = window.parent.arasTabs;';
		script.textContent += 'window.opener = window.parent;';
		script.textContent += close;
		script.textContent += focus;
		win.document.body.appendChild(script);
	};

	var openReportInTab = function(mode, report_location, url) {
		var winName = self.mainWindowName + '_' + self.getItemProperty(report, 'id');
		var win;
		mode = mode || 'tab';

		if (mode === 'tab' && report_location !== 'service') {
			winName = winName + '_' + Date.now();
		}

		var mainWindowDoc = self.getMainWindow().document;
		var frame = mainWindowDoc.getElementById(winName);

		if (!frame) {
			win = tabsObj.open(url || aras.getScriptsURL() + 'blank.html', winName);
			tabsObj.updateTitleTab(winName, {label: self.getItemProperty(report, 'name'), image: '../images/TabDefault.svg'});

		} else {
			win = frame.contentWindow;
			win.focus();
		}

		if (report_location !== 'service') {
			win.document.write(results);
			win.document.write('<br>');
			win.document.body.style.background = '#fff';
		}

		if (!win.tabsObj) {
			url ? win.frameElement.addEventListener('load', createScript.bind(null, win)) : createScript(win);
		}

		return win;
	};

	var reportItemType = report.getAttribute('type');
	var isSsrsReport = report_location === 'service' && reportItemType === 'Report';
	var isIe11 = window.MSInputMethodContext && document.documentMode;

	if (target == 'window') {

		if (tabsObj && !(isIe11 && isSsrsReport)) {
			return openReportInTab('tab', report_location, url);
		}

		var width = 800, // This is a printable page width.
			height = screen.availHeight / 2,
			x = (screen.availHeight - height) / 2,
			y = (screen.availWidth - width) / 2,
			args = 'scrollbars=yes,resizable=yes,status=yes,width=' + width + ',height=' + height + ',left=' + y + ',top=' + x;

		if (report_location == 'service') {

			var win = open(url, '', args);
			if (doReturnWindow) {
				return win;
			}
			return;

		}

		var win = open('', '', args);
		doc = win.document.open();
		var name = this.getItemProperty(report, 'label');
		if (!name) {
			name = this.getItemProperty(report, 'name');
		}
		name = this.getResource('', 'aras_object.report_with_label', name);
		doc.write(results);
		doc.close();
		win.document.title = name;
		if (doReturnWindow) {
			return win;
		}
	} else if (target == 'main') {
		var mainWindow = this.getMainWindow();
		if (this.Browser.isCh()) {
			this.makeItemsGridBlank();
		}
		if (report_location == 'service') {

			var container = '<iframe width=\'100%\' height=\'100%\' frameborder=\'0\' src=\'' + url + '\'></iframe>';
			doc = mainWindow.work.document.open();
			doc.write(container);
			doc.close();
			return;
		}
		doc = mainWindow.work.document.open();
		doc.write(results);
		doc.close();
	} else if (target == 'none') {
		return;
	} else if (target == 'one window') {

		if (tabsObj && !(isIe11 && isSsrsReport)) {
			return openReportInTab('one tab', report_location, url);
		}

		var targetWindow;

		if (report_location == 'service') {
			targetWindow = this.getActionTargetWindow(name, url);
			return;

		}

		targetWindow = this.getActionTargetWindow(name);
		doc = targetWindow.document;
		doc.write(results);
		doc.write('<br>');
	}
};

/**
 * Invoke the Method associated with a report.
 * @param report the the Report item
 * @param itemTypeID is ignored
 */
Aras.prototype.runClientReport = function Aras_runClientReport(report, itemTypeID, item) {
	if (!report) {
		this.AlertError(this.getResource('', 'aras_object.failed_get_report'), '', '');
		return;
	}

	var results = '';
	var selectedItem = item;

	report = this.getItemFromServer('Report', report.getAttribute('id'), 'label,name,description,report_query,target,type,xsl_stylesheet,location,method(name,method_type,method_code)').node;

	var reportType = this.getItemProperty(report, 'type');
	var methodName = this.getItemPropertyAttribute(report, 'method', 'keyed_name');

	if (methodName) {
		results = reportType == 'item' ? this.evalItemMethod(methodName, selectedItem) : this.evalMethod(methodName, '');
	} else {
		var report_query = this.getItemProperty(report, 'report_query');

		if (!report_query) {
			if (reportType == 'item') {
				report_query = '<Item typeId=\'{@typeId}\' id=\'{@id}\' action=\'get\' levels=\'1\'/>';
			} else if (reportType == 'itemtype') {
				report_query = '<Item typeId=\'{@typeId}\' action=\'get\'/>';
			} else if (reportType == 'generic') {
				report_query = '';
			}
		}

		if (report_query) {
			var xslt = '<xsl:stylesheet xmlns:xsl=\'http://www.w3.org/1999/XSL/Transform\' version=\'1.0\'>' +
				'<xsl:output method=\'xml\' omit-xml-declaration=\'yes\' standalone=\'yes\' indent=\'yes\'/>' +
				'	<xsl:template match=\'/\'>' +
				'		<xsl:apply-templates/>' +
				'	</xsl:template>' +
				'	<xsl:template match=\'Item\'>' + report_query + '</xsl:template>' +
				'</xsl:stylesheet>';
			var itemDom = this.createXMLDocument();

			if (item) {
				itemDom.loadXML(item.xml);
			}

			var query = this.applyXsltString(itemDom, xslt);
			if (query) {
				results = this.applyItem(query);
			} else {
				results = this.applyItem(report_query);
			}

			var xsl_stylesheet = this.getItemProperty(report, 'xsl_stylesheet');
			if (xsl_stylesheet) {
				var xslt_stylesheetDOM = this.createXMLDocument();
				xslt_stylesheetDOM.loadXML(xsl_stylesheet);

				var toolLogicNode = xslt_stylesheetDOM.selectSingleNode('//script[@userData="Tool Logic"]');
				if (toolLogicNode) {
					toolLogicNode.parentNode.removeChild(toolLogicNode);
				}

				xsl_stylesheet = xslt_stylesheetDOM.xml;

				var res = this.createXMLDocument();
				res.loadXML(results);

				if (reportType == 'item') {
					res.loadXML('<Result>' + results + '</Result>');
				} else {
					res.loadXML(results);
				}

				results = this.applyXsltString(res, xsl_stylesheet);
			}
		}
	}

	return results;
};

Aras.prototype.runServerReport = function Aras_runServerReport(report, itemTypeID, item) {
	if (!report) {
		this.AlertError(this.getResource('', 'aras_object.failed_get_report'), '', '');
		return;
	}

	var report_name = this.getItemProperty(report, 'name');

	var AML = '';
	if (item) {
		var item_copy = item.cloneNode(true);
		if (itemTypeID) {
			item_copy.setAttribute('typeId', itemTypeID);
		}
		AML = item_copy.xml;
	} else if (itemTypeID) {
		AML = '<Item typeId=\'' + itemTypeID + '\'/>';
	}

	var body = '<report_name>' + report_name + '</report_name><AML>' + AML + '</AML>';
	var results = this.applyMethod('Run Report', body);

	return results;
};

/**
 * Method to set the value of an element on the node
 * and set action attribute on the node, if it is absent.
 * The item is the node and the property is the element.
 * @param {*} srcNode the item object
 * @param {string} element the property to set
 * @param {*} value the value for the property
 * @param {boolean} [apply_the_change_to_all_found=true] flag to signal if the change must be common or local
 * @param {string} [action='update'] action attribute to be set on the node. By default, if action is not defined
 * and node action attribute != 'add' or != 'create' we set action 'update'
 */
Aras.prototype.setNodeElementWithAction = function Aras_setNodeElementWithAction(srcNode, element, value, apply_the_change_to_all_found, action) {
	this.setNodeElement(srcNode, element, value, apply_the_change_to_all_found);

	if (!srcNode.getAttribute('action') || (srcNode.getAttribute('action') != 'add') && (srcNode.getAttribute('action') != 'create')) {
		if (action) {
			srcNode.setAttribute('action', action);
		} else {
			srcNode.setAttribute('action', 'update');
		}
	}
};

/**
 * Method to set the value of an element on the node.
 * The item is the node and the property is the element.
 * @param {*} srcNode the item object
 * @param {string} element the property to set
 * @param {*} value the value for the property
 * @param {boolean} [applyTheChangeToAllFound=true] flag to signal if the change must be common or local
 * @param {*} [itemTypeNd=undefined] node representing itemType of srcNode
 * @return {boolean} always true.
 */
Aras.prototype.setNodeElement = Aras.prototype.setItemProperty = function Aras_setItemProperty(srcNode, element, value, applyTheChangeToAllFound, itemTypeNd) {
	if (applyTheChangeToAllFound === undefined) {
		applyTheChangeToAllFound = true;
	}

	const propertyName = element;
	const propertyValue = (value == null) ? '' : value;

	const currDate = new Date();
	const LastModifiedOn = currDate.getTime();

	var skipSourceNode = false;
	const id = srcNode.getAttribute('id');
	var propertyValueWasTransfered = false;

	if (applyTheChangeToAllFound) {
		const nodes = this.itemsCache.getItemsByXPath('//Item[@id=\'' + id + '\']');
		for (let i = 0; i < nodes.length; i++) {
			const node = nodes[i];
			if (node === srcNode) {
				skipSourceNode = true;
			}
			_setItemProperty(this, node, propertyName, itemTypeNd, propertyValue);
		}
	}

	if (!skipSourceNode) {
		_setItemProperty(this, srcNode, propertyName, itemTypeNd, propertyValue);
	}

	const nds2MarkAsDirty = srcNode.selectNodes('ancestor-or-self::Item');
	for (let i = 0; i < nds2MarkAsDirty.length; i++) {
		const node = nds2MarkAsDirty[i];
		if (this.isLockedByUser(node)) {
			node.setAttribute('isDirty', '1');
		}
	}

	return true;

	function isEmptyElement(xmlElem) {
		if (xmlElem) {
			if (xmlElem.hasChildNodes() || xmlElem.attributes.length !== 0) {
				return false;
			}
		}
		return true;
	}

	function getPropertyDataType(arasObj, itemTypeName, propertyName, itemTypeNode) {
		const itemType = itemTypeNode ? itemTypeNode : arasObj.getItemTypeForClient(itemTypeName).node;
		if (!itemType) {
			return '';
		}

		const dataType = itemType.selectSingleNode('Relationships/Item[@type="Property"][name="' + propertyName + '"]/data_type');
		if (dataType) {
			return dataType.text;
		}

		return '';
	}

	function _setItemProperty(arasObj, node, propertyName, itemTypeNode, propertyValue) {
		var elm = node.selectSingleNode(propertyName);
		if (!elm) {
			elm = node.appendChild(node.ownerDocument.createElement(propertyName));
		}
		if (elm.getAttribute('is_null') !== '') {
			elm.removeAttribute('is_null');
		}

		const elementWasEmpty = isEmptyElement(elm);

		var itemType = '';
		var valueIsNode;
		if (propertyValue.xml == undefined) {
			valueIsNode = false;
			elm.text = propertyValue;
		} else {
			valueIsNode = true;
			elm.text = '';

			var value2use = propertyValue;

			//check if we insert node into itself
			itemType = propertyValue.getAttribute('type');
			const itemId = propertyValue.getAttribute('id');
			const propertyValueClones = value2use.selectNodes('ancestor-or-self::Item[@type=\'' + itemType + '\' and @id=\'' + itemId + '\']');
			var isACopyOfParent = false;
			for (var i = 0; i < propertyValueClones.length; i++) {
				if (propertyValue == propertyValueClones[i]) {
					isACopyOfParent = true;
					break;
				}
			}

			if (isACopyOfParent || propertyValueWasTransfered) {
				value2use = value2use.cloneNode(true);
			}

			propertyValueWasTransfered = true;
			elm.appendChild(value2use);
		}

		var updateKeyedName = false;
		if (elm.getAttribute('keyed_name') !== null) {
			updateKeyedName = true;
		} else if (elementWasEmpty) {
			const srcItemType = srcNode.getAttribute('type');
			if (srcItemType) {
				if (getPropertyDataType(arasObj, srcItemType, propertyName, itemTypeNode) == 'item') {
					updateKeyedName = true;
				}
			}
		}

		if (updateKeyedName) {
			var newKeyedName;
			if (valueIsNode) {
				newKeyedName = arasObj.getKeyedNameEx(propertyValue);
			} else {
				var propertyItemType = elm.getAttribute('type');
				if (propertyItemType == null) {
					propertyItemType = '';
				}
				newKeyedName = arasObj.getKeyedName(propertyValue, propertyItemType);
			}

			elm.setAttribute('keyed_name', newKeyedName);

			elm.removeAttribute('discover_only');
			if (propertyValue) {
				var cachedItem = null;
				if (itemType == 'ItemType') {
					cachedItem = arasObj.getItemTypeDictionary((valueIsNode ? propertyValue.getAttribute('id') : propertyValue), 'id');
					if (cachedItem && cachedItem.node) {
						cachedItem = cachedItem.node;
					}
				} else {
					cachedItem = arasObj.itemsCache.getItem(valueIsNode ? propertyValue.getAttribute('id') : propertyValue);
				}

				if (cachedItem && cachedItem.getAttribute('discover_only') == '1') {
					elm.setAttribute('discover_only', '1');
				}
			}

			if (valueIsNode) {
				const oldKeyedName = arasObj.getItemProperty(propertyValue, 'keyed_name');
				if (!oldKeyedName && newKeyedName) {
					arasObj.setItemProperty(propertyValue, 'keyed_name', newKeyedName, false);
				}
			}
		}

		node.setAttribute('LastModifiedOn', LastModifiedOn);
	}
};

/**
 * Method to get the value of an element on the node.
 * The item is the node and the property is the element.
 * @param {*} node the item object
 * @param {string} element the property to set
 * @param {string} [defaultVal]
 */
Aras.prototype.getItemProperty = Aras.prototype.getNodeElement = function(node, element, defaultVal) {
	if (!node) {
		return;
	}
	var value;
	if (node.nodeName == 'Item' && element == 'id') {
		value = node.getAttribute('id');
	} else {
		var tmpNd = node.selectSingleNode(element);
		if (tmpNd) {
			var tmpNd2 = tmpNd.selectSingleNode('Item');
			if (tmpNd2) {
				value = tmpNd2.getAttribute('id');
			} else {
				value = tmpNd.text;
			}
		} else {
			value = (defaultVal === undefined ? '' : defaultVal);
		}
	}
	return value;
};

Aras.prototype.setNodeTranslationElement = Aras.prototype.setItemTranslation = function Aras_setItemTranslation(srcNode, mlPropNm, value, lang) {
	var pNd;
	this.getItemTranslation(srcNode, mlPropNm, lang, null, function(foundNode) {
		pNd = foundNode;
	});

	if (!pNd) {
		pNd = this.browserHelper.createTranslationNode(srcNode, mlPropNm, this.translationXMLNsURI, this.translationXMLNdPrefix);
		pNd = srcNode.appendChild(pNd);
		pNd.setAttribute('xml:lang', lang);
	}

	if (value === null || value === undefined) {
		value = '';
		pNd.setAttribute('is_null', '1');
	}
	pNd.text = value;
};

Aras.prototype.getNodeTranslationElement = Aras.prototype.getItemTranslation = function Aras_getItemTranslation(srcNode, mlPropNm, lang, defaultVal, foundNodeCb) {
	var pNd = this.browserHelper.getNodeTranslationElement(srcNode, mlPropNm, this.translationXMLNsURI, lang);
	if (foundNodeCb) {
		foundNodeCb(pNd);
	}
	if (!pNd) {
		return (defaultVal === undefined ? '' : defaultVal);
	}
	return pNd.text;
};

Aras.prototype.setNodeTranslationElementAttribute = Aras.prototype.setItemTranslationAttribute = function Aras_setItemTranslationAttribute(srcNode, mlPropNm, lang, attribute, value) {
	this.getItemTranslation(srcNode, mlPropNm, lang, null, function(foundNode) {
		if (foundNode) {
			foundNode.setAttribute(attribute, value);
		}
	});
};

Aras.prototype.getNodeTranslationElementAttribute = Aras.prototype.getItemTranslationAttribute = function Aras_getItemTranslationAttribute(srcNode, mlPropNm, lang, attribute, defaultVal) {
	var r;
	this.getItemTranslation(srcNode, mlPropNm, lang, null, function(foundNode) {
		if (foundNode) {
			r = foundNode.getAttribute(attribute);
		}
	});

	if (r === undefined) {
		r = (defaultVal === undefined ? '' : defaultVal);
	}
	return r;
};

Aras.prototype.removeItemTranslation = function Aras_removeItemTranslation(srcNode, mlPropNm, lang) {
	this.getItemTranslation(srcNode, mlPropNm, lang, null, function(foundNode) {
		if (foundNode) {
			srcNode.removeChild(foundNode);
		}
	});
};

Aras.prototype.removeNodeTranslationElementAttribute = Aras.prototype.removeItemTranslationAttribute = function Aras_setItemTranslationAttribute(srcNode, mlPropNm, lang, attribute) {
	this.getItemTranslation(srcNode, mlPropNm, lang, null, function(foundNode) {
		if (foundNode) {
			foundNode.removeAttribute(attribute);
		}
	});
};

/**
 * Method to set the value of an attribute on an element on the node.
 * The item is the node and the property is the element.
 * @param node the item object
 * @param {string} element the property to set
 * @param {string} attribute the name of the attribute
 * @param {string} value the value for the attribute
 */
Aras.prototype.setNodeElementAttribute = Aras.prototype.setItemPropertyAttribute = function(node, element, attribute, value) {
	if (!node) {
		return;
	}
	var elm = node.selectSingleNode(element);
	if (elm) {
		elm.setAttribute(attribute, value);
	} else {
		this.newNodeElementAttribute(node, element, attribute, value);
	}
};

/**
 * Method to get the value of an attribute on an element on the node.
 * The item is the node and the property is the element.
 * @param node the item object
 * @param {string} element the property to get
 * @param {string } attribute the name of the attribute
 */
Aras.prototype.getNodeElementAttribute = Aras.prototype.getItemPropertyAttribute = function(node, element, attribute) {
	if (!node) {
		return null;
	}
	var value = null;
	var elm = node.selectSingleNode(element);
	if (!elm) {
		return null;
	} else {
		value = elm.getAttribute(attribute);
	}
	return value;
};

Aras.prototype.removeNodeElementAttribute = Aras.prototype.removeItemPropertyAttribute = function(node, element, attribute) {
	var elm = node.selectSingleNode(element);
	if (elm) {
		elm.removeAttribute(attribute);
	}
};

/**
 * Method to create a new element (property) for the item node and set the value of an attribute on an element on the node.
 * The item is the node and the property is the element.
 * @param node the item object
 * @param {string} element the property to set
 * @param {string} attribute the name of the attribute
 * @param {string} value the value for the attribute
 */
Aras.prototype.newNodeElementAttribute = Aras.prototype.newItemPropertyAttribute = function(node, element, attribute, value) {
	var elm = this.createXmlElement(element, node);
	elm.setAttribute(attribute, value);
	return elm;
};

/**
 * Method to get the text value for an element by XPath.
 * @param {string} xpath the APath to the element
 * @param node the optional node otherwise use the global dom
 */
Aras.prototype.getValueByXPath = function(xpath, node) {
	if (arguments.length < 2) {
		var node = this.dom;
	}
	if (!node.selectSingleNode(xpath)) {
		return;
	}
	return node.selectSingleNode(xpath).text;
};

/**
 * Method to load a ItemType by Form ID
 * @param {string} id the id for the Form item
 * @param {boolean} [ignoreFault=false]
 */
Aras.prototype.getItemTypeByFormID = function(id, ignoreFault) {
	if (ignoreFault == undefined) {
		ignoreFault = false;
	}
	var res = this.soapSend('GetItemTypeByFormID', '<Item id="' + id + '" />');

	if (res.getFaultCode() != 0) {
		if (!ignoreFault) {
			this.AlertError(res);
		}
		return false;
	}

	var itemTypeID = res.results.selectSingleNode('//Item').getAttribute('id');
	return this.getItemTypeDictionary(itemTypeID, 'id').node;
};

/**
 * Method to set the users working directory
 * @param {string} id the id for the user
 * @param {string} workingDir the working directory
 */
Aras.prototype.setUserWorkingDirectory = function(id, workingDir) {
	var elm = this.createXmlElement('Item');
	elm.setAttribute('id', id);
	elm.setAttribute('workingDir', workingDir);
	var res = this.soapSend('SetUserWorkingDirectory', elm.xml);
	if (res.getFaultCode() != 0) {
		this.AlertError(res);
		return false;
	}
};

/**
 * Method to get the next value from a sequence item
 * @param {string} id the id for the sequence (optional if seqName is used)
 * @param {string} seqName the sequence name (optional is the id is used)
 */
Aras.prototype.getNextSequence = function(id, seqName) {
	if (id == undefined) {
		id = '';
	}

	var body = '<Item';
	if (id != '') {
		body += ' id="' + id + '"';
	}
	body += '>';
	if (seqName != undefined) {
		body += '<name>' + seqName + '</name>';
	}
	body += '</Item>';

	var res = this.soapSend('GetNextSequence', body);
	if (res.getFaultCode() != 0) {
		this.AlertError(res);
		return false;
	}

	return res.results.selectSingleNode(this.XPathResult()).text;
};

/**
 * Method to get list of identity IDs for those current user is a member.
 * The list is a string and has following format:
 * identityID,identityID,...,identityID
 */
Aras.prototype.buildIdentityList = function Aras_buildIdentityList(identityListSoapResults) {
	if (identityListSoapResults.getFaultCode() != 0) {
		this.AlertError(identityListSoapResults);
		this.setIdentityList('');
	} else {
		this.setIdentityList(identityListSoapResults.results.selectSingleNode(this.XPathResult()).text);
	}
	return this.getIdentityList();
};

Aras.prototype.applySortOrder = function Aras_applySortOrder(relationshipsArray) {
	//this method is for internal purposes only.
	var arasObj = this;
	function sortOrderComparer(nd1, nd2) {
		var sortOrder1 = parseInt(arasObj.getItemProperty(nd1, 'sort_order'));
		if (isNaN(sortOrder1)) {
			return 1;
		}

		var sortOrder2 = parseInt(arasObj.getItemProperty(nd2, 'sort_order'));
		if (isNaN(sortOrder2)) {
			return -1;
		}

		if (sortOrder1 > sortOrder2) {
			return 1;
		} else if (sortOrder1 == sortOrder2) {
			return 0;
		}
		return -1;
	}

	//relationshipsArray.sort(sortOrderComparer); doesn't work sometimes with error "Object doesn't support this property or method".
	//in debugger I see that relationshipsArray.sort is defined but call relationshipsArray.sort() throws the exception

	//work around:
	var tmpArray = [];
	for (var i = 0; i < relationshipsArray.length; i++) {
		tmpArray.push(relationshipsArray[i]);
	}

	tmpArray.sort(sortOrderComparer);

	for (var i = 0; i < relationshipsArray.length; i++) {
		relationshipsArray[i] = tmpArray[i];
	}

	tmpArray = null;
};

Aras.prototype.getSeveralListsValues = function Aras_getSeveralListsValues(listsArray, is_bgrequest, readyResponseIfNeed) {
	//this method is for internal purposes only.
	var res = {};
	var listIds = [];
	var filterListIds = [];
	var listsArrayCopy = [];
	var typesArray = {};

	for (var i = 0; i < listsArray.length; i++) {
		var listDescr = listsArray[i];
		var listId = listDescr.id;
		var relType = listDescr.relType;
		typesArray[listId] = relType;

		if (is_bgrequest && !readyResponseIfNeed) {
			var listDescrCopy = {id: listId, relType: relType};
			listsArrayCopy.push(listDescrCopy);
		}
		var key = this.MetadataCache.CreateCacheKey('getSeveralListsValues-' + relType, listId);
		if (!this.MetadataCache.GetItem(key)) {
			if (relType == 'Value') {
				listIds.push(listId);
			} else if (relType == 'Filter Value') {
				filterListIds.push(listId);
			}
		}
	}

	var response = readyResponseIfNeed;
	if ((listIds.length != 0) || (filterListIds.length != 0)) {
		if (!response) {
			response = this.MetadataCache.GetList(listIds, filterListIds);
		}

		if (response.getFaultCode() != 0) {
			return res;
		}

		var items = response.results.selectNodes(this.XPathResult('/Item'));
		for (var i = 0; i < items.length; i++) {
			var listNd = items[i];
			var id = this.getItemProperty(listNd, 'id');
			var key = this.MetadataCache.CreateCacheKey('getSeveralListsValues-' + typesArray[id], id);
			this.MetadataCache.SetItem(key, listNd);
		}
	}

	for (var i = 0; i < listsArray.length; i++) {
		var valuesArr = [];
		var listDescr = listsArray[i];
		var listId = listDescr.id;
		var key = this.MetadataCache.CreateCacheKey('getSeveralListsValues-' + typesArray[listId], listId);
		var listNode = this.MetadataCache.GetItem(key);
		if (listNode) {
			var values = listNode.selectNodes('Relationships/Item');
			for (var j = 0; j < values.length; j++) {
				valuesArr.push(values[j]);
			}

			this.applySortOrder(valuesArr);

			res[listNode.getAttribute('id')] = valuesArr;
		}
	}

	// 1) add stubs for not found lists
	// 2) mark lists as requested in the session for preloading in future sessions
	for (var i = 0; i < listsArray.length; i++) {
		var listDescr = listsArray[i];
		var listId = listDescr.id;
		var relType = listDescr.relType;
		if (res[listId] === undefined) {
			res[listId] = [];
		}
	}

	return res;
};

Aras.prototype.getListValues_implementation = function Aras_getListValues_implementation(listID, relType, is_bgrequest) {
	//this method is for internal purposes only.
	var listsArray = [];
	var listDescr = {};
	listDescr.id = listID;
	listDescr.relType = relType;
	listsArray.push(listDescr);

	var res = this.getSeveralListsValues(listsArray, is_bgrequest);

	return res[listID];
};

/**
 * Method to get the Values for a List item
 * @param {string} listId the id for the List
 * @param {boolean} is_bgrequest
 */
Aras.prototype.getListValues = function Aras_getListValues(listID, is_bgrequest) {
	return this.getListValues_implementation(listID, 'Value', is_bgrequest);
};

/**
 * Method to get the Filter Value for a List item
 * @param {string} listID the id for the List
 * @param {boolean} is_bgrequest
 */
Aras.prototype.getListFilterValues = function Aras_getListFilterValues(listID, is_bgrequest) {
	return this.getListValues_implementation(listID, 'Filter Value', is_bgrequest);
};

/**
 * Method to clear the server cache
 */
Aras.prototype.clearCache = function() {
	var res = this.soapSend('ClearCache', '<Item />');
	if (res.getFaultCode() != 0) {
		this.AlertError(res);
		return false;
	}
	return true;
};

/**
 * Method to get the style for the item
 * @param item dom object for the item
 */
Aras.prototype.getItemStyles = function(item) {
	if (!item) {
		return null;
	}

	var css = this.getItemProperty(item, 'css');
	if (css == '') {
		return null;
	}

	var res = {};
	var styles = css.split('\n');
	var styleTmplt = new RegExp(/^\.(\w)+(\s)*\{(\w|\s|\:|\-|\#|\;)*\}$/);

	for (var i = 0; i < styles.length; i++) {
		var style = styles[i];
		if (!styleTmplt.test(style)) {
			continue;
		}

		var tmp = style.split('{');
		var styleNm = tmp[0].substr(1).replace(/\s/g, '');

		var propertiesStr = tmp[1].substr(0, tmp[1].length - 1);
		var properties = propertiesStr.split(';');
		var styleObj = {};

		for (var j = 0; j < properties.length; j++) {
			tmp = properties[j].split(':');
			if (tmp.length == 2) {
				var propNm = tmp[0].replace(/\s/g, '');
				var propVl = tmp[1].replace(/\s/g, '');
				if (propNm) {
					styleObj[propNm] = propVl;
				}
			}
		}

		res[styleNm] = styleObj;
	}

	return res;
};

/**
 * Method to to apply the item style to teh grid cell
 * @param cell the grid cell object
 * @param {Object} style the style for the cell
 * @param {boolean} setBg boolean to set the background for the cell
 */
Aras.prototype.applyCellStyle = function(cell, style, setBg) {
	if (style['color']) {
		cell.setTextColor(style['color']);
	}
	if (setBg && style['background-color']) {
		cell.setBgColor_Experimental(style['background-color']);
	}
	if (style['font-family']) {
		var font = style['font-family'].split(',')[0];
		if (style['font-size']) {
			font += '-' + style['font-size'].split('p')[0];
		}
		cell.setFont(font);
	}
	if (style['font-weight'] && style['font-weight'] == 'bold') {
		cell.setTextBold();
	}
};

Aras.prototype.preserveTags = function(str) {
	if (str == undefined) {
		return;
	}

	if (str == '') {
		return str;
	}

	str = str.replace(/&/g, '&amp;');
	str = str.replace(/</g, '&lt;');
	str = str.replace(/>/g, '&gt;');

	return str;
};

Aras.prototype.escapeXMLAttribute = function(strIn) {
	if (strIn == undefined) {
		return;
	}

	if (strIn == '') {
		return strIn;
	}

	strIn = strIn.replace(/&/g, '&amp;');
	strIn = strIn.replace(/</g, '&lt;');
	strIn = strIn.replace(/>/g, '&gt;');
	strIn = strIn.replace(/"/g, '&quot;');
	strIn = strIn.replace(/'/g, '&apos;');

	return strIn;
};

/**
 * Returns a pointer to the main Aras object (from the main window)
 */
Aras.prototype.findMainArasObject = function Aras_findMainArasObject() {
	var isMainWindow = (this.getMainWindow().name == this.mainWindowName);

	if (!isMainWindow) {
		if (this.parentArasObj) {
			return this.parentArasObj.findMainArasObject();
		} else {
			var topWnd = this.getMostTopWindowWithAras(window);
			if (topWnd.opener && !this.isWindowClosed(topWnd.opener) && topWnd.opener.topWnd.aras) {
				return topWnd.opener.topWnd.aras.findMainArasObject();
			}
		}
	}

	return this;
};

/**
 * Register Handler for event by win
 * see fireEvent description for details
 */
Aras.prototype.registerEventHandler = function Aras_registerEventHandler(eventName, win, handler) {
	var EvHandlers;

	var topWnd = this.getMostTopWindowWithAras();

	try {
		EvHandlers = topWnd['Event Handlers'];
	}
	catch (excep) {
		return false;
	}

	if (!EvHandlers) {
		topWnd.eval('window[\'Event Handlers\'] = {};');
		EvHandlers = topWnd['Event Handlers'];
	}

	if (!EvHandlers[eventName]) {
		topWnd.eval('window[\'Event Handlers\'][\'' + eventName + '\'] = [];');
	}

	EvHandlers[eventName].push(handler);

	return true;
};

/**
 * UnRegister Handler for event by win
 */
Aras.prototype.unregisterEventHandler = function Aras_unregisterEventHandler(eventName, win, handler) {
	var EvHandlers;

	var topWnd = this.getMostTopWindowWithAras();

	try {
		EvHandlers = topWnd['Event Handlers'];
	}
	catch (excep) {
		return false;
	}

	if (!EvHandlers) {
		return true;
	}

	var handlersArr = EvHandlers[eventName];
	if (!handlersArr) {
		return true;
	}

	for (var i = 0; i < handlersArr.length; i++) {
		if (handlersArr[i] == handler) {
			handlersArr.splice(i, 1);
			return true;
		}
	}

	return false;
};

/**
 * fires event in all windows
 * supported events:
 * "VariableChanged": {varName, varValue}
 * "ItemLock": {itemID, itemNd, newLockedValue}
 * "ItemSave": {itemID, itemNd}
 * @param {string} eventName
 * @param params
 */
Aras.prototype.fireEvent = function Aras_fireEvent(eventName, params) {
	var mainAras = this.findMainArasObject();
	if (this != mainAras) {
		return mainAras.fireEvent(eventName, params);
	}

	if (!eventName) {
		return false;
	}

	var topWindow = this.getMostTopWindowWithAras(window);

	for (var winId in this.windowsByName) {
		if (!this.windowsByName.hasOwnProperty(winId)) {
			continue;
		}

		var win = null;
		try {
			win = this.windowsByName[winId];
			if (this.isWindowClosed(win)) {
				continue;
			}
			if (this.getMostTopWindowWithAras(win) == topWindow) {
				continue;
			}
		}
		catch (excep) {
			continue;
		}

		var EvHandlers = null;
		try {
			EvHandlers = this.getMostTopWindowWithAras(win)['Event Handlers'];
			if (!EvHandlers) {
				continue;
			}
		}
		catch (excep) {
			continue;
		}

		var handlersArr = EvHandlers[eventName];
		if (!handlersArr) {
			continue;
		}

		for (var i = 0; i < handlersArr.length; i++) {
			try {
				handlersArr[i](params);
			}
			catch (excep) {
			}
		}
	}

	var EvHandlers = topWindow['Event Handlers'];
	if (!EvHandlers) {
		return true;
	}

	var handlersArr = EvHandlers[eventName];
	if (!handlersArr) {
		return true;
	}

	var handlers2Remove = [];

	for (var i = 0; i < handlersArr.length; i++) {
		var f = handlersArr[i];
		try {
			f(params);
		}
		catch (e) {
			 // it's IE error code that means that a context of the method (handlersArr[i]) has already been freed and the method cannot be executed. Usually it would happen if window/iframe in which this method was
			 // initialized was destroyed/closed. It would be better unregister such handlers after its window/iframe was destroyed/closed so that this error isn't occur at all.
			var resourceHasBeenFreedExceptionNumberInIE = -2146823277; // "Can't execute code from a freed script" IE error
			if (e.number == resourceHasBeenFreedExceptionNumberInIE || this.Browser.isCh()) {
				// temporary fix for issue IR-039156 "No save after remove row from BOM tab".
				// The problem is that in Chrome browser "Can't execute code from a freed script" error hasn't a particular number/code so there is no possibility
				// to understand that exactly this error has occured. So as a temp fix all errors in Chrome will not be thrown as an exception.
				// todo In Innovator 12 we must remove this part of code (isCh() if) and make unregistering of 'ItemSaveListener' eventHandler on 'unload' event from Solutions/PLM/Import/Form/Part MultiLevel BOM.xml
				handlers2Remove.push(f);
			} else {
				throw e;
			}
		}
	}

	for (var i = handlers2Remove.length - 1; i >= 0; i--) {
		this.unregisterEventHandler(eventName, topWindow, handlers2Remove[i]);
	}
};

Aras.prototype.getCurrentWindow = function Aras_getCurrentWindow() {
	return window;
};

Aras.prototype.getMainWindow = function Aras_getMainWindow() {
	try {
		var mainWindow = this.getCommonPropertyValue('mainWindow');
		if (mainWindow) {
			return mainWindow;
		}

		var topWindowWithAras = this.getMostTopWindowWithAras(window);
		var isMainWindow = (topWindowWithAras.name == this.mainWindowName);
		if (isMainWindow) {
			return topWindowWithAras;
		}

		//this function is to avoid explicit "top" usage
		function getTopWindow(windowObj) {
			var win = windowObj ? windowObj : window;
			while (win !== win.parent) {
				//We should not care about any cross-domain case since "main window" case is not considered here
				win = win.parent;
			}
			return win;
		}

		var topWnd = getTopWindow(), topWnd2;
		if (topWnd.opener && !this.isWindowClosed(topWnd.opener)) {
			topWnd2 = this.getMostTopWindowWithAras(topWnd.opener);
			topWnd2 = this.isWindowClosed(topWnd2) ? null : topWnd2;
		}
		if (!topWnd2) {
			topWnd2 = this.getMostTopWindowWithAras(topWnd.dialogOpener);
			topWnd2 = this.isWindowClosed(topWnd2) ? null : topWnd2;
		}

		return topWnd2 ? topWnd2.aras.getMainWindow() : topWnd;
	}
	catch (excep) {
		return null;
	}
};

Aras.prototype.getMainArasObject = function Aras_getMainArasObject() {
	var res = null;

	var mainWnd = this.getMainWindow();
	if (mainWnd && !this.isWindowClosed(mainWnd)) {
		res = mainWnd.aras;
	}

	return res;
};

Aras.prototype.newQryItem = function Aras_newQryItem(itemTypeName) {
	var mainArasObj = this.getMainArasObject();

	if (mainArasObj && mainArasObj != this) {
		return mainArasObj.newQryItem(itemTypeName);
	} else {
		var topWnd = this.getMostTopWindowWithAras(window);
		return (new topWnd.QryItem(topWnd.aras, itemTypeName));
	}
};

Aras.prototype.newObject = function Aras_newObject() {
	var mainArasObj = this.getMainArasObject();

	if (mainArasObj && mainArasObj != this) {
		return mainArasObj.newObject();
	} else {
		return ({});
	}
};
Aras.prototype.deletePropertyFromObject = function Aras_deletePropertyFromObject(obj, key) {
	if (key in obj) {
		return delete obj[key];
	}
	return true;
};

Aras.prototype.newIOMItem = function Aras_newIOMItem(itemTypeName, action) {
	return this.IomInnovator.newItem(itemTypeName, action);
};

Aras.prototype.newIOMInnovator = function Aras_newIOMInnovator(contextAras) {
	var mainArasObj = this.getMainArasObject();
	if (mainArasObj && mainArasObj != this) {
		return mainArasObj.newIOMInnovator(this);
	} else {
		//It's important to pass InnovatorServerConnector constructor by *contextAras* instead of *mainArasObj* so that IE could properly work with files selected by a user.
		//A problem is that in IE we have no access to files created by any other window.
		//So reading/sending/saving of the files must be performed in a context of the window created the files
		//because for each new window there is a new Vault object (that is contained in own arasObject) and this Vault object works with files of the window.
		//Note: previously each instance of InnovatorServerConnector was passed only by *mainArasObj*.
		var connector = new Aras.IOM.InnovatorServerConnector(contextAras || this);
		return this.IomFactory.CreateInnovator(connector);
	}
};

Aras.prototype.newArray = function Aras_newArray() {
	var mainArasObj = this.getMainArasObject();

	if (mainArasObj && mainArasObj != this) {
		var str2eval = '';
		for (var i = 0; i < arguments.length; i++) {
			str2eval += 'args[' + i + '],';
		}
		if (str2eval != '') {
			str2eval = str2eval.substr(0, str2eval.length - 1);
		}
		str2eval = 'return mainArasObj.newArray(' + str2eval + ');';

		var f = new Function('mainArasObj', 'args', str2eval);
		return f(mainArasObj, arguments);
	} else {
		var res;
		if (arguments.length == 1) {
			res = new Array(arguments[0]);
		} else {
			res = [];
			for (var i = 0; i < arguments.length; i++) {
				res.push(arguments[i]);
			}
		}

		res.concat = function newArray_concat() {
			var resArr = [];
			for (var i = 0; i < this.length; i++) {
				resArr[i] = this[i];
			}

			for (var i = 0; i < arguments.length; i++) {
				if (arguments[i].pop) {
					for (var j = 0; j < arguments[i].length; j++) {
						resArr.push(arguments[i][j]);
					}
				} else {
					resArr.push(arguments[i]);
				}
			}

			return resArr;
		};

		return res;
	}
};

Aras.prototype.getFileItemTypeID = function Aras_getFileItemTypeID() {
	return this.getItemTypeId('File');
};

Aras.prototype.cloneForm = function Aras_cloneForm(formID, newFormName) {
	if (!formID || !newFormName) {
		return false;
	}

	var bodyStr = '<Item type="Form" id="' + formID + '" newFormName="' + newFormName + '" do_lock="true" />';
	var res = null;

	with (this) {
		var statusId = showStatusMessage('status', getResource('', 'aras_object.copying_form'), system_progressbar1_gif);
		res = soapSend('CloneForm', bodyStr);
		clearStatusMessage(statusId);
	}

	if (res.getFaultCode() != 0) {
		var win = this.uiFindWindowEx(formID);
		if (!win) {
			win = window;
		}
		this.AlertError(res, win);
		return false;
	}

	return true;
};

/**
 * Return Vault Server url for current User
 * @returns {string}
 */
Aras.prototype.getVaultServerURL = function Aras_getVaultServerURL() {
	var vaultServerID = this.getVaultServerID();
	if (!vaultServerID) {
		return '';
	}

	if (this.vaultServerURL != undefined) {
		return this.vaultServerURL;
	}

	var vaultNd = this.itemsCache.getItem(vaultServerID) || this.getItemById('Vault', vaultServerID, 0, '', 'vault_url,name');
	if (!vaultNd) {
		return '';
	}

	var vaultServerURL = this.getItemProperty(vaultNd, 'vault_url');
	this.VaultServerURL = this.TransformVaultServerURL(vaultServerURL);
	return this.VaultServerURL;
};

Aras.prototype.TransformVaultServerURL = function Aras_TransformVaultServerURL(url) {
	var xform_url = this.VaultServerURLCache[url];
	if (xform_url != undefined) {
		return (xform_url);
	}

	var res = this.soapSend('TransformVaultServerURL', '<url>' + url + '</url>');

	if (res.getFaultCode() != 0) {
		this.AlertError(res);
		return url;
	}

	var rb = res.getResult();
	xform_url = rb.text;

	var vaultBaseUrl = xform_url + '/..';

	this.VaultServerURLCache[url] = xform_url;
	return xform_url;
};

/**
 * Get Vault Server ID for current User
 * @returns {string} id of Vault Server
 */
Aras.prototype.getVaultServerID = function Aras_getVaultServerID() {
	var userNd = null;
	var tmpUserID = this.getCurrentUserID();

	if (tmpUserID == this.getUserID()) {
		userNd = this.getLoggedUserItem();
	} else {
		userNd = getItemFromServer('User', tmpUserID, 'default_vault').node;
	}

	if (!userNd) {
		return '';
	}

	var vaultServerID = this.getItemProperty(userNd, 'default_vault');
	return vaultServerID;
};

/**
 * Create Xml Element. If parent variable exist, add element as child
 * @param {string} elName element name to be created
 * @param {} parent parent element
 * @returns {}
 */
Aras.prototype.createXmlElement = function(elName, parent) {
	var doc = this.createXMLDocument();
	var element = doc.createElement(elName);
	if (parent) {
		parent.appendChild(element);
	}
	return element;
};

/**
 * provide simple way to create xml documents without specifing needed attributes each time
 */
Aras.prototype.createXMLDocument = function Aras_createXMLDocument() {
	var mainArasObj = this.getMainArasObject();

	if (mainArasObj && mainArasObj != this) {
		return mainArasObj.createXMLDocument();
	} else {
		return new XmlDocument();
	}
};

/**
 * check if xmldom (soap message) contains Fault
 * @param xmlDom xml document with soap message
 * @param {boolean} ignoreZeroFault ignore zero faultcode or not
 * @returns {boolean}
 */
Aras.prototype.hasFault = function Aras_hasFault(xmlDom, ignoreZeroFault) {
	if (ignoreZeroFault) {
		return (xmlDom.selectSingleNode(this.XPathFault('[faultcode!=\'0\']')) != null);
	} else {
		return (xmlDom.selectSingleNode(this.XPathFault()) != null);
	}

};

/**
 * get text with fault details
 * @param xmlDom xml document with soap message
 * @returns {string}
 */
Aras.prototype.getFaultDetails = function Aras_getFaultDetails(xmlDom) {
	var fdNd = xmlDom.selectSingleNode(this.XPathFault('/detail'));

	if (fdNd == null) {
		return '';
	} else {
		return fdNd.text;
	}
};

/**
 * Get text with faultstring
 * @param xmlDom xml document with soap message
 * @returns {string}
 */
Aras.prototype.getFaultString = function Aras_getFaultString(xmlDom) {
	var fdNd = xmlDom.selectSingleNode(this.XPathFault('/faultstring'));

	if (fdNd == null) {
		return '';
	} else {
		return fdNd.text;
	}
};

/**
 * get text with faultactor (contains stack trace)
 * @param xmlDom xml document with soap message
 * @returns {string}
 */
Aras.prototype.getFaultActor = function Aras_getFaultActor(xmlDom) {
	var fdNd = xmlDom.selectSingleNode(this.XPathFault('/detail/legacy_faultactor'));

	if (fdNd == null) {
		return '';
	} else {
		return fdNd.text;
	}
};

Aras.prototype.isInCache = function Aras_isInCache(itemID) {
	return this.itemsCache.hasItem(itemID);
};

Aras.prototype.addToCache = function Aras_addToCache(item) {
	if (!item) {
		return (new CacheResponse(false, this.getResource('', 'aras_object.nothing_to_add'), item));
	}

	var itemID = item.getAttribute('id');
	if (this.isInCache(itemID)) {
		return (new CacheResponse(false, this.getResource('', 'aras_object.already_in_cache'), this.getFromCache(itemID)));
	}

	this.itemsCache.addItem(item);
	return (new CacheResponse(true, '', this.getFromCache(itemID)));
};

Aras.prototype.updateInCache = function Aras_updateInCache(item) {
	if (!item) {
		return (new CacheResponse(false, this.getResource('', 'aras_object.nothing_to_update'), item));
	}

	var itemID = item.getAttribute('id');
	this.itemsCache.updateItem(item);
	return (new CacheResponse(true, '', this.getFromCache(itemID)));
};

Aras.prototype.updateInCacheEx = function Aras_updateInCacheEx(oldItm, newItm) {
	if (!oldItm) {
		return this.addToCache(newItm);
	}
	if (!newItm) {
		return (new CacheResponse(false, this.getResource('', 'aras_object.nothing_to_update'), newItm));
	}

	var itemID = newItm.getAttribute('id');
	this.itemsCache.updateItemEx(oldItm, newItm);
	return (new CacheResponse(true, '', this.getFromCache(itemID)));
};

Aras.prototype.removeFromCache = function Aras_removeFromCache(item) {
	if (!item) {
		return (new CacheResponse(false, this.getResource('', 'aras_object.nothing_to_remove'), item));
	}

	var paramType = typeof (item);
	var itemID;
	if (paramType == 'string') {
		itemID = item;
	} else if (paramType == 'object') {
		itemID = item.getAttribute('id');
	}

	if (this.isInCache(itemID)) {
		this.itemsCache.deleteItem(itemID);
	}

	return (new CacheResponse(true, '', null));
};

Aras.prototype.getFromCache = function getFromCache(itemID) {
	if (!itemID) {
		return null;
	} else {
		return this.itemsCache.getItem(itemID);
	}
};

Aras.prototype.isPropFilledOnServer = function isPropFilledOnServer(propName) {
	if (!propName) {
		return false;
	}

	var props = '^permission_id$|^created_on$|^created_by_id$|^config_id$';
	return (propName.search(props) != -1);
};

Aras.prototype.generateExceptionDetails = function Aras_generateExceptionDetails(err, func) {
	var resXMLDOM = this.createXMLDocument();

	resXMLDOM.loadXML('<Exception />');

	var callStackCounter = 0;
	var callStack = null;

	function addChNode(pNode, chName, chValue) {
		var tmp = pNode.appendChild(resXMLDOM.createElement(chName));
		if (chValue != '') {
			tmp.text = chValue;
		}
		return tmp;
	}

	function getFunctionName(func) {
		if (!func) {
			return this.getResource('', 'aras_object.incorrect_parameter');
		}
		if (typeof (func) != 'function') {
			return this.getResource('', 'aras_object.not_function');
		}

		var funcDef = func.toString();
		funcDef = funcDef.replace(/\/\*([^\*\/]|\*[^\/]|\/)*\*\//g, '');
		funcDef = funcDef.replace(/^\s\/\/.*$/gm, '');

		/^function([^\(]*)/.exec(funcDef);
		var funcName = RegExp.$1;
		funcName = funcName.replace(/\s/g, '');

		return funcName;
	}

	function addCallStackEntry(aCaller) {
		var funcName;
		var funcBody;

		if (aCaller) {
			funcName = getFunctionName(aCaller);
			funcBody = aCaller.toString();
		} else {
			funcName = 'global code';
			funcBody = 'unknown';
		}

		var fNd = addChNode(callStack, 'function', '');
		fNd.setAttribute('name', funcName);
		fNd.setAttribute('order', callStackCounter);

		var callArgsNd = addChNode(fNd, 'call_arguments', '');
		if (aCaller) {
			for (var i = 0; i < aCaller.arguments.length; i++) {
				var argVal = aCaller.arguments[i];
				var argType = 'string';

				if (argVal != undefined) {
					if (argVal.xml != undefined) {
						argType = 'xml';
						argVal = argVal.xml;
					}
				}

				var argNd = addChNode(callArgsNd, 'argument', argVal);
				argNd.setAttribute('order', i);
				argNd.setAttribute('type', argType);
			}
		}

		addChNode(fNd, 'body', funcBody);

		callStackCounter++;
	}

	var root = resXMLDOM.documentElement;
	try {
		addChNode(root, 'number', err.number);
		addChNode(root, 'message', err.message);

		var aCaller = func;
		callStack = addChNode(root, 'call_stack', '');

		while (aCaller) {
			addCallStackEntry(aCaller);
			aCaller = aCaller.caller;
			if (aCaller.caller.length) {
				break;
			}
		}
		addCallStackEntry(aCaller);
	}
	catch (ex2) {
		root.text = ex2.message;
	}

	return resXMLDOM.xml;
};

Aras.prototype.showExceptionDetails = function Aras_showExceptionDetails(err) {
	var anErr = err;
	var aCaller = this.showExceptionDetails.caller;

	var xmlDesc = this.generateExceptionDetails(anErr, aCaller);

	var xmlDoc = this.createXMLDocument();
	xmlDoc.loadXML(xmlDesc);
	var exNd = xmlDoc.selectSingleNode('//Exception');
	if (!exNd) {
		return;
	}
	var self = this;

	var htmlPrefix =
	'<html><head><style type="text/css">' +
	'.h1 {font-size:150%;}.h2 {font-size:120%;}pre {float:left;}</style></head>' +
	'<scr' +
	'ipt>function f(){window.clipboardData.setData("Text", document.getElementById("ta").value);}</scr' +
	'ipt>' +
	'<body>' +
	'<table cellpadding="0" cellspacing="0" width="100%">' +
	'<tr><td colspan="2" class="h1">Exception&nbsp;<input type="button" value="Copy Details" onclick="f()"/></td></tr>' +
	'<tr><td class="h2">Number&nbsp;</td><td width="100%"><pre>' + getNdVal(exNd.selectSingleNode('number')) + '</pre></td></tr>' +
	'<tr><td class="h2">Message&nbsp;</td><td><pre>' + getNdVal(exNd.selectSingleNode('message')) + '</pre></td></tr>' +
	'<tr><td class="h2" valign="top">Details</td><td style="width:100%;height:300;"><textarea id="ta" style="width:400;height:95%;" readonly>';
	var htmlSfx = '</textarea></td></tr>' +
	'</table>' +
	'</body></html>';
	htmlPrefix = htmlPrefix.replace(/'/g, '\\\\\\\'');

	truncateExDetails();

	var maxHtmlLen = 2070;
	var dtls = exNd.xml;
	dtls = dtls.replace(/'/g, '\\\\\\\'');
	var maxLen = maxHtmlLen - htmlPrefix.length - htmlSfx.length - 4;
	if (maxLen > 0 && dtls && dtls.length > maxLen) {
		dtls = dtls.substr(0, maxLen) + '...';
	}

	if (maxLen <= 0) {
		dtls = '';
	}

	var html = htmlPrefix + dtls + htmlSfx;
	if (html.length > maxHtmlLen) {
		html = html.substr(0, maxHtmlLen);
	}

	var options = {
		dialogWidth: 500,
		dialogHeight: 450,
		center: true,
		resizable: true,
		content: "javascript:'" + html + "'"
	};
	window.ArasModules.Dialog.show("iframe", options);

	function getNdVal(nd) {
		if (!nd) {
			return '';
		}

		return self.EscapeSpecialChars(nd.text);
	}
	function truncateExDetails() {
		var nd;
		var nds = exNd.selectNodes('call_stack/function/body');
		for (var i = 0; i < nds.length; i++) {
			nd = nds[i];
			if (nd.text && nd.text.length > 80) {
				nd.text = nd.text.substr(0, 80) + '...';
			}
		}
		nds = exNd.selectNodes('call_stack/function/call_arguments/argument');
		for (var i = 0; i < nds.length; i++) {
			nd = nds[i];
			if (nd.text && nd.text.length > 20) {
				nd.text = nd.text.substr(0, 30) + '...';
			}
		}
	}
};

Aras.prototype.copyRelationship = function Aras_copyRelationship(relationshipType, relationshipID) {
	var relResult = this.getItemById(relationshipType, relationshipID, 0, undefined);
	var sourceType = this.getItemPropertyAttribute(relResult, 'source_id', 'type');
	var sourceID = this.getItemProperty(relResult, 'source_id');
	var sourceKeyedName = this.getItemPropertyAttribute(relResult, 'source_id', 'keyed_name');

	var relatedItem = this.getRelatedItem(relResult);

	var relatedType = '';
	var relatedID = '';
	var relatedKeyedName = '';

	if (!relatedItem || (relatedItem && '1' == relatedItem.getAttribute('is_polymorphic'))) {
		var relType = this.getRelationshipType(this.getRelationshipTypeId(relationshipType));
		if (!relType || relType.isError()) {
			return;
		}

		relatedType = this.getItemPropertyAttribute(relType.node, 'related_id', 'name');
		relatedKeyedName = this.getItemPropertyAttribute(relType.node, 'related_id', 'keyed_name');
	} else {
		relatedID = relatedItem.getAttribute('id');
		relatedType = relatedItem.getAttribute('type');
		relatedKeyedName = this.getItemProperty(relatedItem, 'keyed_name');
	}

	var clipboardItem = this.newObject();
	clipboardItem.source_id = sourceID;
	clipboardItem.source_itemtype = sourceType;
	clipboardItem.source_keyedname = sourceKeyedName;
	clipboardItem.relationship_id = relationshipID;
	clipboardItem.relationship_itemtype = relationshipType;
	clipboardItem.related_id = relatedID;
	clipboardItem.related_itemtype = relatedType;
	clipboardItem.related_keyedname = relatedKeyedName;

	return clipboardItem;
};

Aras.prototype.pasteRelationship = function Aras_pasteRelationship(parentItem, clipboardItem, as_is, as_new, targetRelationshipTN, targetRelatedTN, showConfirmDlg) {
	var self = this;

	function getProperties4ItemType(itemTypeName) {
		if (!itemTypeName) {
			return;
		}

		var qryItem = new Item('ItemType', 'get');
		qryItem.setAttribute('select', 'name');
		qryItem.setAttribute('page', 1);
		qryItem.setAttribute('pagesize', 9999);
		qryItem.setProperty('name', itemTypeName);

		var relationshipItem = new Item();
		relationshipItem.setType('Property');
		relationshipItem.setAction('get');
		relationshipItem.setAttribute('select', 'name,data_type');
		qryItem.addRelationship(relationshipItem);

		var results = qryItem.apply();
		if (results.isError()) {
			self.AlertError(result);
			return;
		}

		return results.getRelationships('Property');
	}

	function setRelated(targetItem) {
		if (relatedType && relatedType !== 'File') {
			var relatedItemType = self.getItemTypeForClient(relatedType, 'name');
			if (relatedItemType.getProperty('is_dependent') == '1') {
				as_new = true;
			}

			if (as_new == true) {
				var queryItemRelated = new Item();
				queryItemRelated.setType(relatedType);
				queryItemRelated.setID(relatedID);
				queryItemRelated.setAttribute('do_add', '0');
				queryItemRelated.setAttribute('do_lock', '0');
				queryItemRelated.setAction('copy');
				var newRelatedItem = queryItemRelated.apply();
				if (newRelatedItem.isError()) {
					self.AlertError(self.getResource('', 'aras_object.failed_copy_related_item', newRelatedItem.getErrorDetail()), newRelatedItem.getErrorString(), newRelatedItem.getErrorSource());
					return false;
				}
				targetItem.setRelatedItem(newRelatedItem);
			}
		}
	}

	if (as_is == undefined || as_new == undefined) {
		var qryItem4RelationshipType = new Item();
		qryItem4RelationshipType.setType('RelationshipType');
		qryItem4RelationshipType.setProperty('name', relationshipType);
		qryItem4RelationshipType.setAction('get');
		qryItem4RelationshipType.setAttribute('select', 'copy_permissions, create_related');
		var RelNode = qryItem4RelationshipType.apply();
		if (as_is == undefined) {
			as_is = (RelNode.getProperty('copy_permissions') == '1');
		}
		if (as_new == undefined) {
			as_new = (RelNode.getProperty('create_related') == '1');
		}
	}

	var statusId = this.showStatusMessage('status', this.getResource('', 'aras_object.pasting_in_progress'), system_progressbar1_gif);
	if (!clipboardItem) {
		return;
	}

	var relationshipType = clipboardItem.relationship_itemtype;
	var relationshipID = clipboardItem.relationship_id;
	var relatedID = clipboardItem.related_id;
	var relatedType = clipboardItem.related_itemtype;

	if (relationshipType == targetRelationshipTN) {
		var qryItem4CopyRelationship = new Item();
		qryItem4CopyRelationship.setType(relationshipType);
		qryItem4CopyRelationship.setID(relationshipID);
		qryItem4CopyRelationship.setAction('copy');
		qryItem4CopyRelationship.setAttribute('do_add', '0');
		qryItem4CopyRelationship.setAttribute('do_lock', '0');

		var newRelationship = qryItem4CopyRelationship.apply();
		if (newRelationship.isError()) {
			this.AlertError(this.getResource('', 'aras_object.copy_operation_failed', newRelationship.getErrorDetail()), newRelationship.getErrorString(), newRelationship.getErrorSource());
			this.clearStatusMessage(statusId);
			return false;
		}
		newRelationship.removeProperty('source_id');

		if (newRelationship.getType() == 'Property' && newRelationship.getProperty('data_type') == 'foreign') {
			newRelationship.removeProperty('data_source');
			newRelationship.removeProperty('foreign_property');
		}

		setRelated(newRelationship);

		if (!parentItem.selectSingleNode('Relationships')) {
			parentItem.appendChild(parentItem.ownerDocument.createElement('Relationships'));
		}
		var res = parentItem.selectSingleNode('Relationships').appendChild(newRelationship.node.cloneNode(true));
		this.clearStatusMessage(statusId);
		parentItem.setAttribute('isDirty', '1');
		return res;
	}
	var topWnd = this.getMostTopWindowWithAras(window);
	var item = new topWnd.Item(relationshipType, 'get');
	item.setID(relationshipID);
	var sourceItem = item.apply();

	if (sourceItem.getAttribute('isNew') == '1') {
		this.AlertError(this.getResource('', 'aras_object.failed_get_source_item'), '', '');
		this.clearStatusMessage(statusId);
		return false;
	}
	sourceRelationshipTN = sourceItem.getType();

	var targetItem = new Item();
	targetItem.setType(sourceRelationshipTN);
	targetItem.setAttribute('typeId', sourceItem.getAttribute('typeId'));

	if (targetRelationshipTN == undefined) {
		targetRelationshipTN = sourceRelationshipTN;
	}

	if (sourceRelationshipTN != targetRelationshipTN) {
		if ((!targetRelatedTN && !relatedType) || targetRelatedTN == relatedType) {
			if (showConfirmDlg) {
				var convert = this.confirm(this.getResource('', 'aras_object.you_attempting_paste_different_relationship_types', sourceRelationshipTN, targetRelationshipTN));
				if (!convert) {
					this.clearStatusMessage(statusId);
					return this.getResource('', 'aras_object.user_abort');
				}
			}
			targetItem.setType(targetRelationshipTN);
		} else {
			this.clearStatusMessage(statusId);
			return false;
		}
	}

	targetItem.setNewID();
	targetItem.setAction('add');
	targetItem.setAttribute('isTemp', '1');
	parentItem.setAttribute('isDirty', '1');

	var sourceProperties = getProperties4ItemType(sourceRelationshipTN);
	var targetProperties = getProperties4ItemType(targetRelationshipTN);

	var srcCount = sourceProperties.getItemCount();
	var trgCount = targetProperties.getItemCount();

	var sysProperties =
		'^id$|' +
		'^created_by_id$|' +
		'^created_on$|' +
		'^modified_by_id$|' +
		'^modified_on$|' +
		'^classification$|' +
		'^keyed_name$|' +
		'^current_state$|' +
		'^state$|' +
		'^locked_by_id$|' +
		'^is_current$|' +
		'^major_rev$|' +
		'^minor_rev$|' +
		'^is_released$|' +
		'^not_lockable$|' +
		'^css$|' +
		'^source_id$|' +
		'^behavior$|' +
		'^sort_order$|' +
		'^config_id$|' +
		'^new_version$|' +
		'^generation$|' +
		'^managed_by_id$|' +
		'^owned_by_id$|' +
		'^history_id$|' +
		'^relationship_id$';

	if (as_is != true) {
		sysProperties += '|^permission_id$';
	}

	var regSysProperties = new RegExp(sysProperties, 'ig');
	for (var i = 0; i < srcCount; i++) {
		var sourceProperty = sourceProperties.getItemByIndex(i);
		var srcPropertyName = sourceProperty.getProperty('name');
		var srcPropertyDataType = sourceProperty.getProperty('data_type');

		if (srcPropertyName.search(regSysProperties) != -1) {
			continue;
		}

		for (var j = 0; j < trgCount; ++j) {
			var targetProperty = targetProperties.getItemByIndex(j);
			var trgPropertyName = targetProperty.getProperty('name');
			var trgPropertyDataType = targetProperty.getProperty('data_type');

			if ((srcPropertyName == trgPropertyName) && (srcPropertyDataType == trgPropertyDataType)) {
				var item = sourceItem.getPropertyItem(srcPropertyName);
				if (!item) {
					var value = sourceItem.getProperty(srcPropertyName);
					targetItem.setProperty(srcPropertyName, value);
				} else {
					targetItem.setPropertyItem(srcPropertyName, item);
				}
				break;
			}
		}
	}
	setRelated(targetItem);
	if (!parentItem.selectSingleNode('Relationships')) {
		parentItem.appendChild(parentItem.ownerDocument.createElement('Relationships'));
	}
	var res = parentItem.selectSingleNode('Relationships').appendChild(targetItem.node.cloneNode(true));
	this.clearStatusMessage(statusId);
	return res;
};

Aras.prototype.isLCNCompatibleWithRT = function Aras_isLastCopyNodeCompatibleWithRelationshipType(targetRelatedTN) {
	var sourceRelatedTN = this.clipboard.getLastCopyRelatedItemTypeName();
	if (!sourceRelatedTN && !targetRelatedTN) {
		return true;
	}
	if (sourceRelatedTN == targetRelatedTN) {
		return true;
	}
	return false;
};

Aras.prototype.isLCNCompatibleWithRTOnly = function Aras_isLastCopyNodeCompatibleWithRelationshipTypeOnly(targetRelationshipTN) {
	var sourceRelationshipTN = this.clipboard.getLastCopyRTName();
	if (!sourceRelationshipTN && !targetRelationshipTN) {
		return true;
	}
	if (sourceRelationshipTN == targetRelationshipTN) {
		return true;
	}
	return false;
};

Aras.prototype.isLCNCompatibleWithIT = function Aras_isLastCopyNodeCompatibleWithItemType(itemTypeID) {
	var clipboardItem = this.clipboard.getLastCopyItem();
	return this.isClItemCompatibleWithIT(clipboardItem, itemTypeID);
};

Aras.prototype.isClItemCompatibleWithIT = function Aras_IsClipboardItemCompatibleWithItemType(clipboardItem, itemTypeID) {
	var RelationshipTypeName = clipboardItem.relationship_itemtype;

	if (!RelationshipTypeName || !itemTypeID) {
		return false;
	}

	return this.getRelationshipTypeId(RelationshipTypeName) != '';
};

Aras.prototype.isClItemCompatibleWithRT = function Aras_IsClipboardItemCompatibleWithRelationshipType(clipboardItem, targetRelatedTN) {
	var sourceRelatedTN = clipboardItem.related_itemtype;
	if (!sourceRelatedTN && !targetRelatedTN) {
		return true;
	}
	if (sourceRelatedTN == targetRelatedTN) {
		return true;
	}
	return false;
};

/**
 * Returns the Active and Pending tasks for the user (Workflow Activities, Project Activities, FMEA Action Items).
 * The users tasks are those assigned to an Identity for which the user is a Member
 * @param {string} inBasketViewMode
 * @param {number} workflowTasks boolean AML value. 1 or 0
 * @param {number} projectTasks boolean AML value. 1 or 0
 * @param {number} actionTasks boolean AML value. 1 or 0
 * @returns {}
 */
Aras.prototype.getAssignedTasks = function(inBasketViewMode, workflowTasks, projectTasks, actionTasks) {
	var body = '<params><inBasketViewMode>' + inBasketViewMode + '</inBasketViewMode>';
	body += '<workflowTasks>' + workflowTasks + '</workflowTasks>';
	body += '<projectTasks>' + projectTasks + '</projectTasks>';
	body += '<actionTasks>' + actionTasks + '</actionTasks></params>';
	var statusId = this.showStatusMessage('status', this.getResource('', 'workflow_methods.getting_user_activities'), system_progressbar1_gif);
	var res = this.soapSend('GetAssignedTasks', body);

	if (statusId != -1) {
		this.clearStatusMessage(statusId);
	}

	if (res.getFaultCode() != 0) {
		this.AlertError(res);
		return false;
	}

	var r = res.getResult().selectSingleNode('./Item').text;
	var s1 = r.indexOf('<thead>');
	var s2 = r.indexOf('</thead>', s1);
	if (r && s1 > -1 && s2 > -1) {
		var s =
			'<thead>' +
			'<th><![CDATA[' + this.getResource('', 'inbasket.locked_column_nm') + ']]></th>' +
			'<th><![CDATA[' + this.getResource('', 'inbasket.type_column_nm') + ']]></th>' +
			'<th><![CDATA[' + this.getResource('', 'inbasket.workflow_project_column_nm') + ']]></th>' +
			'<th><![CDATA[' + this.getResource('', 'inbasket.activity_name_column_nm') + ']]></th>' +
			'<th><![CDATA[' + this.getResource('', 'inbasket.status_column_nm') + ']]></th>' +
			'<th><![CDATA[' + this.getResource('', 'inbasket.start_date_column_nm') + ']]></th>' +
			'<th><![CDATA[' + this.getResource('', 'inbasket.end_date_column_nm') + ']]></th>' +
			'<th><![CDATA[' + this.getResource('', 'inbasket.instrucations_column_nm') + ']]></th>' +
			'<th><![CDATA[' + this.getResource('', 'inbasket.assigned_to_column_nm') + ']]></th>' +
			'</thead>';
		r = r.substr(0, s1) + s + r.substr(s2 + 8);
	}
	return r;
};

Aras.prototype.getFormForDisplay = function Aras_getFormForDisplay(id, mode) {
	// this function is not a part of public API. please do not use it
	var criteriaName = mode == 'by-name' ? 'name' : 'id';
	var resIOMItem;
	// if form is new return form from client cache
	var formNd = this.itemsCache.getItem(id);
	if (formNd && this.isTempEx(formNd)) {
		resIOMItem = this.newIOMItem();
		resIOMItem.dom = formNd.ownerDocument;
		resIOMItem.node = formNd;
		return resIOMItem;
	}

	res = this.MetadataCache.GetForm(id, criteriaName);

	if (res.getFaultCode() != 0) {
		var resIOMError = this.newIOMInnovator().newError(res.getFaultString());
		return resIOMError;
	}

	res = res.getResult();
	resIOMItem = this.newIOMItem();
	resIOMItem.dom = res.ownerDocument;
	resIOMItem.node = res.selectSingleNode('Item');

	// Mark that the item type was requested by main thread in this session
	var ftypeName;
	try {
		ftypeName = resIOMItem.getProperty('name');
	} catch (exc) {
		ftypeName = null;
	}

	return resIOMItem;
};

Aras.prototype.clearClientMetadataCache = function Aras_resetCachedMetadataOnClient() {
	this.MetadataCache.ClearCache();
};

Aras.prototype.getCacheObject = function Aras_getCacheObject() {
	//this is private internal function
	var mainWnd = this.getMainWindow();
	var Cache = mainWnd.Cache;

	if (!Cache) {
		Cache = this.newObject();
		mainWnd.Cache = Cache;
	}

	//for now because there are places where cache is accessed directly instead of call to this function
	if (!Cache.XmlResourcesUrls) {
		Cache.XmlResourcesUrls = this.newObject();
	}
	if (!Cache.UIResources) {
		Cache.UIResources = this.newObject();
	}

	return mainWnd.Cache;
};

/**
 * Search item by specific criteria.
 * @deprecated Use getItemTypeForClient() instead.
 * @param {string} criteriaValue Value of criteria.
 * @param {'id'|'name'} [criteriaName=name] Name of criteria for search. Can be 'id' or 'name'. 'name' by default.
 * @returns {Object}
 */
Aras.prototype.getItemTypeDictionary = function Aras_getItemTypeDictionary(criteriaValue, criteriaName) {
	return this.getItemTypeForClient(criteriaValue, criteriaName);
};

/**
 * Search item by specific criteria.
 * @param {string} criteriaValue Value of criteria.
 * @param {'id'|'name'} [criteriaName=name] Name of criteria for search. Can be 'id' or 'name'. 'name' by default.
 * @returns {Object}
 */
Aras.prototype.getItemTypeForClient = function Aras_getItemTypeForClient(criteriaValue, criteriaName) {
	//this function is a very specific function. please use it only if it is critical for you
	//and there is no another good way to solve your task.
	var res = this.getItemTypeForClientFromCache(criteriaValue, criteriaName);
	if (res.getFaultCode() != 0) {
		var resIOMError = this.newIOMInnovator().newError(res.getFaultString());
		return resIOMError;
	}

	res = res.getResult();
	var resIOMItem = this.newIOMItem();
	resIOMItem.dom = res.ownerDocument;
	resIOMItem.node = res.selectSingleNode('Item');
	return resIOMItem;
};

Aras.prototype.getItemTypeForClientFromCache = function Aras_getItemTypeForClientFromCache(criteriaValue, criteriaName) {
	if (criteriaName === undefined) {
		criteriaName = 'name';
	}

	if (criteriaName !== 'name' && criteriaName !== 'id') {
		throw new Error(1, this.getResource('', 'aras_object.not_supported_criteria', criteriaName));
	}

	var res = this.MetadataCache.GetItemType(criteriaValue, criteriaName);
	if (res.getFaultCode() != 0) {
		this.AlertError(res);
		return res;
	}
	return res;
};

Aras.prototype.getItemTypeNodeForClient = function Aras_getItemTypeNodeForClient(criteriaValue, criteriaName) {
	var res = this.getItemTypeForClientFromCache(criteriaValue, criteriaName);
	if (res.getFaultCode() != 0) {
		var resIOMError = this.newIOMInnovator().newError(res.getFaultString());
		return resIOMError.node;
	}
	return res.getResult().selectSingleNode('Item');
};

Aras.prototype.getItemTypeId = function Aras_getItemTypeId(name) {
	return this.MetadataCache.GetItemTypeId(name);
};

Aras.prototype.getItemTypeName = function Aras_getItemTypeName(id) {
	return this.MetadataCache.GetItemTypeName(id);
};

Aras.prototype.getRelationshipTypeId = function Aras_getRelationshipTypeId(name) {
	return this.MetadataCache.GetRelationshipTypeId(name);
};

Aras.prototype.getRelationshipTypeName = function Aras_getRelationshipTypeId(id) {
	return this.MetadataCache.GetRelationshipTypeName(id);
};

Aras.prototype.getListId = function Aras_getListId(name) {
	var key = this.MetadataCache.CreateCacheKey('getListId', name);
	var result = this.MetadataCache.GetItem(key);
	if (!result) {
		var value = this.getItemFromServerByName('List', name, 'name', false);
		if (!value) {
			return '';
		}

		result = value.getID();
		this.MetadataCache.SetItem(key, result);
	}

	return result;
};

Aras.prototype.getFormId = function Aras_getFormId(name) {
	return this.MetadataCache.GetFormId(name);
};

Aras.prototype.getRelationshipType = function Aras_getRelationshipType(id) {
	var res = this.MetadataCache.GetRelationshipType(id, 'id');
	if (res.getFaultCode() != 0) {
		this.AlertError(res);
	}
	res = res.getResult();

	var resIOMItem = this.newIOMItem();
	resIOMItem.dom = res.ownerDocument;
	resIOMItem.node = res.selectSingleNode('Item');

	return resIOMItem;
};

Aras.prototype.getLanguagesResultNd = function Aras_getLanguagesResultNd() {
	var cacheKey = this.MetadataCache.CreateCacheKey('getLanguagesResultNd', 'Language');
	var cachedItem = this.MetadataCache.GetItem(cacheKey);

	if (cachedItem) {
		return cachedItem.content;
	}

	var res = this.getMainWindow().arasMainWindowInfo.getLanguageResult;
	if (res.getFaultCode() != 0) {
		return null;
	}
	var langs = res.results.selectSingleNode(this.XPathResult(''));

	cachedItem = aras.IomFactory.CreateCacheableContainer(langs, langs);
	this.MetadataCache.SetItem(cacheKey, cachedItem);

	return cachedItem.content;
};

Aras.prototype.getLocalesResultNd = function Aras_getLocalesResultNd() {
	var cacheKey = this.MetadataCache.CreateCacheKey('getLocalesResultNd', 'Locale');
	var cachedItem = this.MetadataCache.GetItem(cacheKey);

	if (cachedItem) {
		return cachedItem.content;
	}

	var res = this.soapSend('ApplyItem', '<Item type=\'Locale\' action=\'get\' select=\'code, name, language\'/>');
	if (res.getFaultCode() != 0) {
		return null;
	}
	var langs = res.results.selectSingleNode(this.XPathResult(''));

	cachedItem = aras.IomFactory.CreateCacheableContainer(langs, langs);
	this.MetadataCache.SetItem(cacheKey, cachedItem);

	return cachedItem.content;
};

Aras.prototype.getItemFromServer = function Aras_getItemFromServer(itemTypeName, id, selectAttr, related_expand, language) {
	if (!related_expand) {
		related_expand = false;
	}
	if (!selectAttr) {
		selectAttr = '';
	}
	var qry = this.getMostTopWindowWithAras(window).Item(itemTypeName, 'get');
	qry.setAttribute('related_expand', (related_expand) ? '1' : '0');
	qry.setAttribute('select', selectAttr);
	qry.setProperty('id', id);
	if (language) {
		qry.setAttribute('language', language);
	}

	var results = qry.apply();

	if (results.isEmpty()) {
		return false;
	}

	if (results.isError()) {
		this.AlertError(results);
		return false;
	}

	return results.getItemByIndex(0);
};

Aras.prototype.getItemFromServerByName = function Aras_getItemFromServer(itemTypeName, name, selectAttr, related_expand) {
	if (!related_expand) {
		related_expand = false;
	}

	var qry = this.newIOMItem(itemTypeName, 'get');
	qry.setAttribute('related_expand', (related_expand) ? '1' : '0');
	qry.setAttribute('select', selectAttr);
	qry.setProperty('name', name);

	var results = qry.apply();

	if (results.isEmpty()) {
		return false;
	}

	if (results.isError()) {
		this.AlertError(results);
		return false;
	}

	return results.getItemByIndex(0);
};

Aras.prototype.getItemFromServerWithRels = function Aras_getItemFromServerWithRels(itemTypeName, id, itemSelect, reltypeName, relSelect, related_expand) {
	if (!related_expand) {
		related_expand = false;
	}

	var qry = this.getMostTopWindowWithAras(window).Item(itemTypeName, 'get');
	qry.setProperty('id', id);
	qry.setAttribute('select', itemSelect);

	if (reltypeName) {
		var topWnd = this.getMostTopWindowWithAras(window);
		var rel = new topWnd.Item(reltypeName, 'get');
		rel.setAttribute('select', relSelect);
		rel.setAttribute('related_expand', (related_expand) ? '1' : '0');
		qry.addRelationship(rel);
	}

	var results = qry.apply();

	if (results.isEmpty()) {
		return false;
	}

	if (results.isError()) {
		this.AlertError(results);
		return false;
	}

	return results.getItemByIndex(0);
};

/**
 * @deprecated
 */
Aras.prototype.getFile = function Aras_getFile(value, fileSelect) {
	var topWnd = this.getMostTopWindowWithAras(window);
	var qry = new topWnd.Item('File', 'get');
	qry.setAttribute('select', fileSelect);
	qry.setID(value);

	var results = qry.apply();

	if (results.isEmpty()) {
		return false;
	}

	if (results.isError()) {
		this.AlertError(results);
		return false;
	}
	return results.getItemByIndex(0);
};

Aras.prototype.refreshWindows = function Aras_refreshWindows(message, results, saveChanges) {
	if (saveChanges == undefined) {
		saveChanges = true;
	}

	// Skip the refresh if this is the unlock portion of the "Save, Unlock and Close" operation.
	if (!saveChanges) {
		return;
	}

	// If no IDs modified then nothing to refresh.
	var nodeWithIDs = message.selectSingleNode('event[@name=\'ids_modified\']');
	if (!(nodeWithIDs && results)) {
		return;
	}

	// Get list of modified IDs
	var IDsArray = nodeWithIDs.getAttribute('value').split('|');

	// Refresh changed items in search tabs grid
	const topWin = this.getMainWindow();
	IDsArray.forEach((function(itemNodeId) {
		//new item
		const itemNode = results.selectSingleNode('//Item[@id=\'' + itemNodeId + '\']');
		if (!itemNode) {
			return;
		}

		const itemTypeId = itemNode.getAttribute('typeId');
		const itemsGrids = topWin.arasTabs.getSearchGridTabs(itemTypeId);
		itemsGrids.forEach((function(itemsGrid) {
			const grid = itemsGrid.grid;
			if (grid.getRowIndex(itemNodeId) === -1) {
				return;
			}
			//old item
			this.refreshItemsGrid(itemNode.getAttribute('type'), itemNodeId, itemNode, itemsGrid);
		}).bind(this));
	}).bind(this));

	// Check if there are any other opened windows, that must be refreshed.
	var doRefresh = false;
	for (var winId in this.windowsByName) {
		var win = null;
		try {
			if (this.windowsByName.hasOwnProperty(winId)) {
				win = this.windowsByName[winId];
				if (this.isWindowClosed(win)) {
					this.deletePropertyFromObject(this.windowsByName, winId);
					continue;
				}

				// Item doesn't updated if it was changed by action(Manual Release, Create New Revision)
				/*if (win.top_ == top_) added "_" to "top" because we removed all the "top" in this file.
				continue;*/

				doRefresh = true;
				break;
			}
		}
		catch (excep) {
			continue;
		}
	}
	// Return if there are no windows to refresh.
	if (!doRefresh) {
		return;
	}

	// Get changed item ID (new Item) or new id=0 if item was deleted.
	var itemNode = results.selectSingleNode('//Item');
	var currentID = 0;
	if (itemNode) {
		currentID = itemNode.getAttribute('id');
	}

	var RefreshedRelatedItems = [];
	var RefreshedItems = {};
	var alreadyRefreshedWindows = {};
	var self = this;

	function refreshWindow(oldItemId, itemNd) {
		if (alreadyRefreshedWindows[oldItemId]) {
			return;
		}

		var win = self.uiFindWindowEx(oldItemId);
		if (!win) {
			return;
		}

		alreadyRefreshedWindows[oldItemId] = true;
		alreadyRefreshedWindows[itemNd.getAttribute('id')] = true; //just fo a case item is versionable
		self.uiReShowItemEx(oldItemId, itemNd);
	}
	var dependency = getTypeIdDependencyForRefreshing(IDsArray);
	refreshVersionableItem(dependency);

	function getTypeIdDependencyForRefreshing(IDsArray) {
		var result = {};
		for (var i in IDsArray) {
			var itemID = IDsArray[i];
			if (currentID == itemID) {
				continue;
			}

			//not locked items with id=itemID *anywhere* in the cache
			var nodes = self.itemsCache.getItemsByXPath('//Item[@id=\'' + itemID + '\' and string(locked_by_id)=\'\']');
			for (var j = 0; j < nodes.length; j++) {
				itemFromDom = nodes[j];
				var type = itemFromDom.getAttribute('type');
				//if type if LCM, Form, WFM, IT or RelshipType or id already refreshed skip adding it to array
				if (type == 'Life Cycle Map' || type == 'Form' || type == 'Workflow Map' || type == 'ItemType' || type == 'RelationshipType' || RefreshedItems[itemID]) {
					continue;
				}

				var cid = itemFromDom.selectSingleNode('config_id');
				var value;
				if (cid) {
					value = {id: itemID, config_id: cid.text};
				} else {
					value = {id: itemID, config_id: undefined};
				}
				if (result[type]) {
					//get structure: type  = Array of {id, config_id}
					result[type].push(value);
				} else {
					result[type] = [];
					result[type].push(value);
				}
			}
		}
		return result;
	}

	function refreshVersionableItem(dependency) {
		for (let e in dependency) {
			const element = dependency[e];
			//e - type. Type contains multiple ids
			//create server request for data:
			/*
			<Item type="e" action="get">
				<config_id condition="in">id1, id2...</config_id>
				<is_current>1</is_current>
			</Item>
			*/
			const configIds = getConfigIdsForRequest(element);
			if (configIds === '') {
				continue;
			}

			const itemsToRefresh = self.loadItems(e, '<config_id condition=\'in\'>' + configIds + '</config_id>' + '<is_current>1</is_current>', 0);
			itemsToRefresh.forEach(function(itemNode) {
				const configId = itemNode.selectSingleNode('config_id').text;
				const id = getOldIdForRefresh(element, configId);
				refreshWindow(id, itemNode);
				const mainWindow = self.getMainWindow();
				self.refreshItemsGrid(e, id, itemNode, mainWindow);
			});
		}
	}

	function getOldIdForRefresh(dependencyArray, configID) {
		for (var i = 0; i < dependencyArray.length; i++) {
			if (dependencyArray[i].config_id == configID) {
				return dependencyArray[i].id;
			}
		}
	}

	function getConfigIdsForRequest(dependencyArray) {
		var preResult = []; //create array of ids for request in order to make request string in the end
		var result = '';
		for (var i = 0; i < dependencyArray.length; i++) {
			if (dependencyArray[i].config_id) {
				preResult.push('\'' + dependencyArray[i].config_id + '\'');
			}
		}
		if (preResult.length > 0) {
			while (preResult.length > 1) {
				result += preResult.pop() + ',';
			}
			result += preResult.pop();
		}
		return result;
	}

	for (var i in IDsArray) {
		var itemID = IDsArray[i];
		//items with related_id=itemID
		var nodes1 = this.itemsCache.getItemsByXPath('//Item[count(descendant::Item[@isTemp=\'1\'])=0 and string(@isDirty)!=\'1\' and Relationships/Item/related_id/Item[@id=\'' + itemID + '\']]');

		nodes = nodes1;
		// processing of items with related_id=itemID
		for (var j = 0; j < nodes.length; j++) {
			var itemNd = nodes[j];
			var id = itemNd.getAttribute('id');
			var type = itemNd.getAttribute('type');
			var bAlreadyRefreshed = false;
			for (var k = 0; k < RefreshedRelatedItems.length; k++) {
				if (id == RefreshedRelatedItems[k]) {
					bAlreadyRefreshed = true;
					break;
				}
			}

			if (bAlreadyRefreshed) {
				continue;
			} else {
				RefreshedRelatedItems.push(id);
			}

			if (id == currentID) {
				continue;
			}

			if (type == 'Life Cycle Map' || type == 'Form' || type == 'Workflow Map' || type == 'ItemType') {
				continue;
			}

			//IR-006509
			if (!this.isDirtyEx(itemNd)) {
				var related_ids = itemNd.selectNodes('Relationships/Item/related_id[Item/@id="' + currentID + '"]'); //get related_id list with items with id=currentID

				//update related_id nodes in cache
				for (var i_r = 0, L = related_ids.length; i_r < L; i_r++) {
					var relshipItem = related_ids[i_r].parentNode;
					var relship_id = relshipItem.getAttribute('id');
					var relship_type = relshipItem.getAttribute('type');
					var res = this.soapSend('GetItem', '<Item type="' + relship_type + '" id="' + relship_id + '" select="related_id"/>', undefined, false);

					if (res.getFaultCode() == 0) {
						var res_related_id = res.getResult().selectSingleNode('Item/related_id/Item[@id="' + currentID + '"]');
						if (res_related_id == null) {
							continue;
						}

						//update attributes and child nodes
						var attr;
						for (var i_att = 0; i_att < res_related_id.attributes.length; i_att++) {
							attr = res_related_id.attributes[i_att];
							related_ids[i_r].setAttribute(attr.nodeName, attr.nodeValue);
						}

						//it more safe than replace node. Because it is possible that there are places where reference to releated_id/Item node
						//is chached in local variable. The replacement would just break the code.
						//mergeItem does not merge attributes in its current implementation. Thus the attributes are copied with the legacy code above.
						this.mergeItem(relshipItem.selectSingleNode('related_id/Item[@id="' + currentID + '"]'), res_related_id);
					}
				}
			}

			const win = this.uiFindWindowEx(id);
			if (win !== window) {
				refreshWindow(id, itemNd);
			}
		} // ^^^ processing of items with related_id=itemID
	}
};

Aras.prototype.refreshItemsGrid = function Aras_refreshItemsGrid(itemTypeName, itemID, updatedItem, itemsGrid) {
	if (!updatedItem || !itemsGrid || !itemsGrid.isItemsGrid) {
		return false;
	}

	const updatedID = updatedItem.getAttribute('id');

	if (itemTypeName === 'ItemType') {
		if (itemID === itemsGrid.itemTypeID) {
			itemsGrid.location.replace('../scripts/blank.html');
			return true;
		}
	}

	if (itemsGrid.itemTypeName !== itemTypeName) {
		return false;
	}

	const grid = itemsGrid.grid;
	if (grid.getRowIndex(itemID) === -1) {
		return true;
	}

	const wasSelected = (grid.getSelectedItemIds().indexOf(itemID) > -1);

	if (updatedID !== itemID) {
		//hack to prevent rewrite deleteRow to use typeName and Id instead of node
		let oldItem = this.createXMLDocument();
		oldItem.loadXML('<Item type=\'' + itemTypeName + '\' id=\'' + itemID + '\'/>');
		oldItem = oldItem.documentElement;

		itemsGrid.deleteRow(oldItem);
	}

	itemsGrid.updateRow(updatedItem);

	if (wasSelected) {
		if (updatedID === itemID) {
			itemsGrid.onSelectItem(itemID);
		} else {
			const currSel = grid.getSelectedId();
			//if (currSel)
			itemsGrid.onSelectItem(currSel);
		}
	} //if (wasSelected)

	return true;
};

Aras.prototype.getDirtyItems = function Aras_getDirtyItems() {
	const dirtyItemsXPath = '/Innovator/Items/Item[@action!=\'\' and (@isTemp=\'1\' or @isEditState=\'1\' or (locked_by_id=\'' + this.getUserID() +
		'\' and (@isDirty=\'1\' or .//Item/@isDirty=\'1\' or .//Item/@isTemp=\'1\'))) and not(@type="mpo_MassPromotion")]';

	return this.itemsCache.getItemsByXPath(dirtyItemsXPath);
};

Aras.prototype.unlockDirtyItems = function Aras_unlockDirtyItems() {
	const dirtyItems = this.getDirtyItems();

	if (!dirtyItems || !dirtyItems.length) {
		return;
	}

	Array.prototype.forEach.call(dirtyItems, function(item) {
		if (!this.isTempEx(item)) {
			this.unlockItemEx(item, false);
		}
	}.bind(this));
};

Aras.prototype.isDirtyItems = function Aras_isDirtyItems() {
	if (this.getCommonPropertyValue('exitWithoutSavingInProgress')) {
		return false;
	}

	return this.getDirtyItems().length > 0;
};

Aras.prototype.dirtyItemsHandler = function Aras_dirtyItemsHandler() {
	if (this.isDirtyItems()) {
		var param = {
			title: this.getResource('', 'dirtyitemslist.unsaved_items'),
			aras: this,
			dialogWidth: 400,
			dialogHeight: 500,
			content: 'dirtyItemsList.html'
		};

		return ArasModules.Dialog.show('iframe', param).promise;
	}
};

Aras.prototype.getPreferenceItem = function Aras_getPreferenceItem(prefITName, specificITorRTId) {
	if (!prefITName) {
		return null;
	}

	var self = this;
	var prefKey;
	if (specificITorRTId) {
		if (prefITName == 'Core_RelGridLayout') {
			var relType = this.getRelationshipType(specificITorRTId).node;
			var itID = specificITorRTId;
			if (relType) {
				itID = this.getItemProperty(relType, 'relationship_id');
			}
			prefKey = this.MetadataCache.CreateCacheKey('Preference', prefITName, specificITorRTId, itID, this.preferenceCategoryGuid);
		} else {
			prefKey = this.MetadataCache.CreateCacheKey('Preference', prefITName, specificITorRTId, this.preferenceCategoryGuid);
		}
	} else {
		prefKey = this.MetadataCache.CreateCacheKey('Preference', prefITName, this.preferenceCategoryGuid);
	}

	var res = this.MetadataCache.GetItem(prefKey);
	if (res) {
		return res.content;
	}

	var findCriteriaPropNm = '';
	var findCriteriaPropVal = specificITorRTId;
	switch (prefITName) {
		case 'Core_ItemGridLayout': {
			findCriteriaPropNm = 'item_type_id';
			break;
		}
		case 'Core_RelGridLayout': {
			findCriteriaPropNm = 'rel_type_id';
			break;
		}
		case 'cmf_ContentTypeGridLayout': {
			findCriteriaPropNm = 'tabular_view_id';
			break;
		}
	}

	function getPrefQueryXml(prefCondition) {
		var xml = '<Item type=\'Preference\' action=\'get\'>';
		xml += prefCondition;

		xml += '<Relationships>';
		xml += '<Item type=\'' + prefITName + '\'>';

		if (findCriteriaPropNm) {
			xml += '<' + findCriteriaPropNm + '>' + findCriteriaPropVal + '</' + findCriteriaPropNm + '>';
		}

		xml += '</Item>';
		xml += '</Relationships></Item>';
		return xml;
	}
	var xml = getPrefQueryXml(inner_getConditionForUser());
	var resDom = this.createXMLDocument();
	var prefMainItemID = this.getVariable('PreferenceMainItemID');
	var prefMainItemDom = this.createXMLDocument();
	var res;
	if (prefITName === 'Core_GlobalLayout') {
		res = this.getMainWindow().arasMainWindowInfo.Core_GlobalLayout;
	} else if (prefITName === 'SSVC_Preferences') {
		res = this.getMainWindow().arasMainWindowInfo.SSVC_Preferences;
	} else if (prefITName === 'ES_Settings') {
		res = this.getMainWindow().arasMainWindowInfo.ES_Settings;
	} else {
		res = this.soapSend('ApplyItem', xml);
		if (res.getFaultCode() != 0) {
			this.AlertError(res);
			return null;
		}
	}
	res = res.getResultsBody();
	if (res && res.indexOf('Item') > -1) {
		resDom.loadXML(res);
		if (!prefMainItemID) {
			prefMainItemDom.loadXML(res);
			var tmpNd = prefMainItemDom.selectSingleNode('/*/Relationships');
			if (tmpNd) {
				tmpNd.parentNode.removeChild(tmpNd);
			}
		}
	}
	if (!resDom.selectSingleNode('//Item[@type=\'' + prefITName + '\']')) {
		xml = getPrefQueryXml(inner_getConditionForSite());
		res = this.soapSend('ApplyItem', xml);
		if (res.getFaultCode() != 0) {
			this.AlertError(res);
			return null;
		}
		var newPref = this.newItem(prefITName);
		var tmp = newPref.cloneNode(true);

		newPref = tmp;
		res = res.getResultsBody();
		if (res && res.indexOf('Item') > -1) {
			resDom.loadXML(res);
			var nds2Copy = resDom.selectNodes('//Item[@type=\'' + prefITName + '\']/*[local-name()!=\'source_id\' and local-name()!=\'permission_id\']');
			for (var i = 0; i < nds2Copy.length; i++) {
				var newNd = newPref.selectSingleNode(nds2Copy[i].nodeName);
				if (!newNd) {
					newNd = newPref.appendChild(newPref.ownerDocument.createElement(nds2Copy[i].nodeName));
				}
				newNd.text = nds2Copy[i].text;
			}
		}
		if (findCriteriaPropNm) {
			var tmpNd = newPref.appendChild(newPref.ownerDocument.createElement(findCriteriaPropNm));
			tmpNd.text = findCriteriaPropVal;
		}
		resDom.loadXML(newPref.xml);
		if (!prefMainItemID) {
			var mainPref = this.newItem('Preference');
			var tmp = mainPref.cloneNode(true);

			mainPref = tmp;
			var userNd = this.getLoggedUserItem();
			identityNd = userNd.selectSingleNode('Relationships/Item[@type=\'Alias\']/related_id/Item[@type=\'Identity\']');
			if (!identityNd) {
				return null;
			}

			this.setItemProperty(mainPref, 'identity_id', identityNd.getAttribute('id'));
			prefMainItemDom.loadXML(mainPref.xml);
		}
	}

	if (!prefMainItemID) {
		var mainPref = prefMainItemDom.documentElement;
		var tmpKey = this.MetadataCache.CreateCacheKey('Preference', mainPref.getAttribute('id'));
		var itm = aras.IomFactory.CreateCacheableContainer(mainPref, mainPref);
		this.MetadataCache.SetItem(tmpKey, itm);
		this.setVariable('PreferenceMainItemID', mainPref.getAttribute('id'));
	}

	var result = resDom.selectSingleNode('//Item[@type=\'' + prefITName + '\']');

	var itm = aras.IomFactory.CreateCacheableContainer(result, result);
	this.MetadataCache.SetItem(prefKey, itm);
	return result;

	function inner_getConditionForSite() {
		var res =
			'<identity_id>' +
			'<Item type=\'Identity\'>' +
			'<name>World</name>' +
			'</Item>' +
			'</identity_id>';
		return res;
	}
	function inner_getConditionForUser() {
		var res;
		var userNd = self.getLoggedUserItem();
		var identityNd = userNd.selectSingleNode('Relationships/Item[@type=\'Alias\']/related_id/Item[@type=\'Identity\']');
		if (!identityNd) {
			return '';
		}

		res = '<identity_id>' + identityNd.getAttribute('id') + '</identity_id>';
		return res;
	}
};

Aras.prototype.getPreferenceItemProperty = function Aras_getPreferenceItemProperty(prefITName, specificITorRTId, propNm, defaultVal) {
	var prefItm = this.getPreferenceItem(prefITName, specificITorRTId);
	return this.getItemProperty(prefItm, propNm, defaultVal);
};

Aras.prototype.setPreferenceItemProperties = function Aras_setPreferenceItemProperties(prefITName, specificITorRTId, varsHash) {
	if (!prefITName || !varsHash) {
		return false;
	}

	var prefNode = this.getPreferenceItem(prefITName, specificITorRTId);
	var varName;
	for (varName in varsHash) {
		var varValue = varsHash[varName];
		var nd = prefNode.selectSingleNode(varName);
		if (!nd) {
			nd = prefNode.appendChild(prefNode.ownerDocument.createElement(varName));
		}
		if (nd.text != varValue) {
			nd.text = varValue;
			var params = {};
			params.type = prefITName;
			params.specificITorRTId = specificITorRTId;
			params.propertyName = varName;
			this.fireEvent('PreferenceValueChanged', params);
		}
	}
	if (varName && !prefNode.getAttribute('action')) {
		prefNode.setAttribute('action', 'update');
	}

	return true;
};

Aras.prototype.savePreferenceItems = function Aras_savePreferenceItems() {
	var prefArr = this.MetadataCache.GetItemsById(this.preferenceCategoryGuid);
	if (!prefArr || prefArr.length < 1) {
		return;
	}

	var prefMainItemID = this.getVariable('PreferenceMainItemID');
	var prefItem;
	if (prefMainItemID) {
		var tmpArr = this.MetadataCache.GetItemsById(prefMainItemID);
		if (tmpArr.length > 0) {
			prefItem = tmpArr[0].content;
		}
	}
	if (!prefItem) {
		return;
	}

	if (!prefItem.getAttribute('action')) {
		prefItem.setAttribute('action', 'edit');
	}

	var rels = prefItem.selectSingleNode('Relationships');
	if (!rels) {
		rels = prefItem.appendChild(prefItem.ownerDocument.createElement('Relationships'));
	}
	var prefItemAction = prefItem.getAttribute('action');
	var i = 0;
	while (prefArr[i]) {
		var nd = prefArr[i].content;
		var ndAction = nd.getAttribute('action');
		if (ndAction) {
			nd = rels.appendChild(nd.cloneNode(true));
			if (ndAction == 'add') {
				var whereArr = [];
				switch (nd.getAttribute('type')) {
					case 'Core_GlobalLayout':
						whereArr.push('[Core_GlobalLayout].source_id=\'' + prefItem.getAttribute('id') + '\'');
						break;
					case 'Core_ItemGridLayout':
						whereArr.push('[Core_ItemGridLayout].source_id=\'' + prefItem.getAttribute('id') + '\'');
						whereArr.push('[Core_ItemGridLayout].item_type_id=\'' + this.getItemProperty(nd, 'item_type_id') + '\'');
						break;
					case 'Core_RelGridLayout':
						whereArr.push('[Core_RelGridLayout].source_id=\'' + prefItem.getAttribute('id') + '\'');
						whereArr.push('[Core_RelGridLayout].rel_type_id=\'' + this.getItemProperty(nd, 'rel_type_id') + '\'');
						break;
				}
				if (whereArr.length) {
					nd.setAttribute('action', 'merge');
					nd.setAttribute('where', whereArr.join(' AND '));
					nd.removeAttribute('id');
				}
			}
		}
		i++;
	}
	if (prefItemAction == 'add') {
		prefItem.setAttribute('action', 'merge');
		prefItem.setAttribute('where', '[Preference].identity_id=\'' + this.getItemProperty(prefItem, 'identity_id') + '\'');
		prefItem.removeAttribute('id');
	}

	prefItem.setAttribute('doGetItem', '0');
	try { this.soapSend('ApplyItem', prefItem.xml); } catch (e) { return; }
	return true;
};

Aras.prototype.mergeItemRelationships = function Aras_mergeItemRelationships(oldItem, newItem) {
	//this method is for internal purposes only.

	var newRelationships = newItem.selectSingleNode('Relationships');
	if (newRelationships != null) {
		var oldRelationships = oldItem.selectSingleNode('Relationships');
		if (oldRelationships == null) {
			oldRelationships = oldItem.appendChild(newRelationships.cloneNode(true));
		} else if (oldRelationships.childNodes.length === 0) {
			oldItem.replaceChild(newRelationships.cloneNode(true), oldRelationships);
		} else {
			this.mergeItemsSet(oldRelationships, newRelationships);
		}
	}
};

Aras.prototype.mergeItem = function Aras_mergeItem(oldItem, newItem) {
	//this method is for internal purposes only.
	var oldId = oldItem.getAttribute('id');
	if (oldId) {
		var newId = newItem.getAttribute('id');
		if (newId && oldId !== newId) {
			return; //do not merge Items with different ids.
		}
	}

	var allPropsXpath = '*[local-name()!=\'Relationships\']';

	var oldAction = oldItem.getAttribute('action');
	if (!oldAction) {
		oldAction = 'skip';
	}

	if (oldAction == 'delete') {
		//do not merge newItem into oldSet
	} else if (oldAction == 'add') {
		//this should never happen because getItem results cannot return not saved Item. do nothing here.
	} else if (oldAction == 'update' || oldAction == 'edit') {
		//we can add only missing properties here and merge relationships
		var newProps = newItem.selectNodes(allPropsXpath);
		for (var i = 0; i < newProps.length; i++) {
			var newProp = newProps[i];

			var propNm = newProp.nodeName;
			var oldProp = oldItem.selectSingleNode(propNm);

			if (!oldProp) {
				oldItem.appendChild(newProp.cloneNode(true));
			} else {
				var oldPropItem = oldProp.selectSingleNode('Item');
				if (oldPropItem) {
					var newPropItem = newProp.selectSingleNode('Item');
					if (newPropItem) {
						this.mergeItem(oldPropItem, newPropItem);
					}
				}
			}
		}

		mergeSpecialAttributes(oldItem, newItem);

		//merge relationships
		this.mergeItemRelationships(oldItem, newItem);
	} else if (oldAction == 'skip') {
		//all properties not containing Items can be replaced here.

		//process oldItem properies with * NO * Item inside
		var oldProps = oldItem.selectNodes(allPropsXpath + '[not(Item)]');
		for (var i = 0; i < oldProps.length; i++) {
			var oldProp = oldProps[i];

			var propNm = oldProp.nodeName;
			var newProp = newItem.selectSingleNode(propNm);

			if (newProp) {
				oldItem.replaceChild(newProp.cloneNode(true), oldProp);
			}
		}

		//process oldItem properies with Item inside
		var oldItemProps = oldItem.selectNodes(allPropsXpath + '[Item]');
		for (var i = 0; i < oldItemProps.length; i++) {
			var oldProp = oldItemProps[i];

			var propNm = oldProp.nodeName;
			var newProp = newItem.selectSingleNode(propNm);

			if (newProp) {
				var oldPropItem = oldProp.selectSingleNode('Item');
				var newPropItem = newProp.selectSingleNode('Item');
				var oldPropItemId = oldPropItem.getAttribute('id');
				if (newPropItem) {
					var newPropItemId = newPropItem.getAttribute('id');
					//id of item may be changed in case of versioning or when item is replaced with another item on server-side
					if (oldPropItemId != newPropItemId) {
						var oldItemHasUnsavedChanges = Boolean(oldPropItem.selectSingleNode('descendant-or-self::Item[@action!=\'skip\']'));
						if (oldItemHasUnsavedChanges) {
							//do nothing. mergeItem will do all it's best.
						} else {
							//set the new id on "old" Item tag
							oldPropItem.setAttribute('id', newPropItemId);

							//content of "old" Item tag is useless. Remove that.
							var children = oldPropItem.selectNodes('*');
							for (var j = 0, C_L = children.length; j < C_L; j++) {
								oldPropItem.removeChild(children[j]);
							}
						}
					}
					this.mergeItem(oldPropItem, newPropItem);
				} else {
					var oldPropItemAction = oldPropItem.getAttribute('action');
					if (!oldPropItemAction) {
						oldPropItemAction = 'skip';
					}

					var newPropItemId = newProp.text;
					if (oldPropItemAction == 'skip') {
						if (newPropItemId != oldPropItemId) {
							oldItem.replaceChild(newProp.cloneNode(true), oldProp);
						}
					}
				}
			}
		}

		//process all newItem properties which are missing in oldItem
		var newProps = newItem.selectNodes(allPropsXpath);
		for (var i = 0; i < newProps.length; i++) {
			var newProp = newProps[i];

			var propNm = newProp.nodeName;
			var oldProp = oldItem.selectSingleNode(propNm);

			if (!oldProp) {
				oldItem.appendChild(newProp.cloneNode(true));
			}
		}

		mergeSpecialAttributes(oldItem, newItem);

		//merge relationships
		this.mergeItemRelationships(oldItem, newItem);
	}

	function mergeSpecialAttributes(oldItem, newItem) {
		var specialAttrNames = new Array('discover_only', 'type');
		for (var i = 0; i < specialAttrNames.length; i++) {
			if (newItem.getAttribute(specialAttrNames[i])) {
				oldItem.setAttribute(specialAttrNames[i], newItem.getAttribute(specialAttrNames[i]));
			}
		}
	}
};

Aras.prototype.mergeItemsSet = function Aras_mergeItemsSet(oldSet, newSet) {
	//this method is for internal purposes only.

	//both oldSet and newSet are nodes with Items inside. (oldSet and newSet normally are AML or Relationships nodes)
	var oldDoc = oldSet.ownerDocument;

	//we don't expect action attribute specified on Items from newSet
	var newItems = newSet.selectNodes('Item[not(@action)]');
	for (var i = 0; i < newItems.length; i++) {
		var newItem = newItems[i];
		var newId = newItem.getAttribute('id');
		var newType = newItem.getAttribute('type');
		var newTypeId = newItem.getAttribute('typeId');

		var oldItem = oldSet.selectSingleNode('Item[@id="' + newId + '"][@type="' + newType + '"]');
		if (!oldItem) {
			//
			oldItem = oldSet.appendChild(oldDoc.createElement('Item'));
			oldItem.setAttribute('id', newId);
			oldItem.setAttribute('type', newType);
			oldItem.setAttribute('typeId', newTypeId);
		}

		this.mergeItem(oldItem, newItem);
	}
};

// +++ Export to Office section +++
//this method is for internal purposes only.
Aras.prototype.export2Office = function Aras_export2Office(gridXmlCallback, toTool, itemNd, itemTypeName, tabName) {
	var statusId = this.showStatusMessage('status', this.getResource('', 'aras_object.exporting'), system_progressbar1_gif);
	var aras = this;
	var contentCallback = function() {
		if (toTool === 'export2excel' || toTool === 'excel') {
			return Export2Excel(typeof (gridXmlCallback) == 'function' ? gridXmlCallback() : gridXmlCallback, itemNd, itemTypeName, tabName);
		}
		return Export2Word(typeof (gridXmlCallback) == 'function' ? gridXmlCallback() : gridXmlCallback, itemNd);
	};

	toTool = toTool && toTool.toLowerCase();

	this.clearStatusMessage(statusId);
	this.saveString2File(contentCallback, toTool);

	function Export2Excel(gridXml, itemNd, itemTypeName, tabName) {
		var result;
		var relatedResult;
		var itemTypeNd;
		var gridDoc = aras.createXMLDocument();
		if (itemNd) {
			itemTypeNd = aras.getItemTypeForClient(itemNd.getAttribute('type'), 'name').node;
		}

		if (!itemTypeName) {
			if (itemTypeNd) {
				itemTypeName = aras.getItemProperty(itemTypeNd, 'name');
			} else {
				itemTypeName = 'Innovator';
			}
		}

		if (!tabName) {
			tabName = 'RelationshipsTab';
		}

		if (gridXml != '') {
			gridDoc.loadXML(gridXml);

			result = generateXML(gridDoc, (itemNd && itemNd.xml) ? tabName : itemTypeName);
		}

		if (itemNd && itemNd.xml && itemTypeNd) {
			var itemTypeID = itemTypeNd.getAttribute('id');
			var resDom = aras.createXMLDocument();
			resDom.loadXML('<Result>' + itemNd.xml + '</Result>');

			var xpath = 'Relationships/Item[@type="Property"]';
			var propNds = itemTypeNd.selectNodes(xpath);

			aras.uiPrepareDOM4GridXSLT(resDom);

			var grid_xml = aras.uiGenerateGridXML(resDom, propNds, null, itemTypeID, {mode: 'forExport2Html'}, true);
			gridDoc.loadXML(grid_xml);

			var tableNd = gridDoc.selectSingleNode('//table');
			if (tableNd.selectSingleNode('thead').childNodes.length == 0) {
				generateThs(gridDoc, propNds);
			}

			if (tableNd.selectSingleNode('columns').childNodes.length == 0) {
				generateColumns(gridDoc, propNds);
			}

			relatedResult = generateXML(gridDoc, itemTypeName);
		}

		//form valid result xml for Excel export
		if (result) {
			if (relatedResult) {
				var relatedDom = aras.createXMLDocument();
				relatedDom.loadXML(relatedResult);
				relatedStyles = relatedDom.documentElement.childNodes[0].childNodes;

				var resultDom = aras.createXMLDocument();
				resultDom.loadXML(result);
				styles = resultDom.documentElement.childNodes[0].childNodes;

				result = '<?xml version="1.0"?><ss:Workbook xmlns:p="urn:ExportBook" xmlns:msxsl="urn:schemas-microsoft-com:xslt" xmlns:usr="urn:the-xml-files:xslt" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"><ss:Styles>';
				//merge all styles from from and relationships grid
				for (var i = 0; i < relatedStyles.length; i++) {
					result += relatedStyles[i].xml;
				}
				for (var j = 0; j < styles.length; j++) {
					result += styles[j].xml;
				}
				result += '</ss:Styles>';

				//merge two worksheets
				result += relatedDom.documentElement.childNodes[1].xml;
				result += resultDom.documentElement.childNodes[1].xml;

				result += '</ss:Workbook>';
			}
		} else {
			if (relatedResult) {
				result = relatedResult;
			} else {
				result = generateXML(gridDoc);
			}
		}
		return result;

		function generateThs(dom, propNds) {
			var parentNode = dom.selectSingleNode('//thead');
			for (var i = 0; i < propNds.length; i++) {
				var pNd = propNds[i];
				var lbl = aras.getItemProperty(pNd, 'label');
				var nm = aras.getItemProperty(pNd, 'name');
				var newTh = parentNode.appendChild(dom.createElement('th'));
				newTh.setAttribute('align', 'c');
				newTh.text = (lbl ? lbl : nm);
			}
			return dom;
		}

		function generateColumns(dom, propNds) {
			var parentNode = dom.selectSingleNode('//columns');
			for (var i = 0; i < propNds.length; i++) {
				var pNd = propNds[i];
				var lbl = aras.getItemProperty(pNd, 'label');
				var nm = aras.getItemProperty(pNd, 'name');
				var type = aras.getItemProperty(pNd, 'data_type');
				var widthAttr = (lbl ? lbl : nm).length * 8;
				var newCol = parentNode.appendChild(dom.createElement('column'));
				if (type == 'date') {
					newCol.setAttribute('sort', 'DATE');
				} else if (type == 'integer' || type == 'float' || type == 'decimal' || type == 'global_version' || type == 'ubigint') {
					newCol.setAttribute('sort', 'NUMERIC');
				}
				newCol.setAttribute('width', widthAttr);
				newCol.setAttribute('order', i);
			}
			return dom;
		}
	}

	function Export2Word(gridXml, itemNd) {
		function generateThs(propNds) {
			var res = '<tr/>';
			var tmpDom = aras.createXMLDocument();
			tmpDom.loadXML(res);
			for (var i = 0; i < propNds.length; i++) {
				var pNd = propNds[i];
				var lbl = aras.getItemProperty(pNd, 'label');
				var nm = aras.getItemProperty(pNd, 'name');
				var newTh = tmpDom.documentElement.appendChild(tmpDom.createElement('th'));
				newTh.setAttribute('align', 'center');
				newTh.setAttribute('style', 'background-color:#d4d0c8;');
				newTh.text = (lbl ? lbl : nm);
			}
			res = tmpDom.xml;
			return res;
		}

		var html = generateHtml(gridXml);
		if (itemNd && itemNd.xml) {
			var itemTypeNd = aras.getItemTypeForClient(itemNd.getAttribute('type'), 'name').node;
			if (itemTypeNd) {
				var itemTypeID = itemTypeNd.getAttribute('id');
				var resDom = aras.createXMLDocument();
				resDom.loadXML('<Result>' + itemNd.xml + '</Result>');

				var xpath = 'Relationships/Item[@type="Property"]';
				var propNds = itemTypeNd.selectNodes(xpath);

				aras.convertFromNeutralAllValues(resDom.selectSingleNode('/Result/Item'));

				aras.uiPrepareDOM4GridXSLT(resDom);
				var grid_xml = aras.uiGenerateGridXML(resDom, propNds, null, itemTypeID, {mode: 'forExport2Html'}, true);
				var tmpHtml = generateHtml(grid_xml);
				if (tmpHtml.indexOf('<th') == -1) {
					var a = tmpHtml.indexOf('<tr');
					tmpHtml = tmpHtml.substr(0, a) + generateThs(propNds) + tmpHtml.substr(a);
				}

				var i = html.indexOf('<table');
				var i2 = tmpHtml.indexOf('<table');
				var i3 = tmpHtml.lastIndexOf('</table>');
				if (i > 0) {
					html = html.substr(0, i) + tmpHtml.substr(i2, i3 - i2 + 8) + '<br/>' + html.substr(i);
				}
			}
		}
		return html;
	}

	function generateHtml(gridXml) {
		var res = '';
		var gridDom = aras.createXMLDocument();
		if (!gridXml) {
			gridXml = '<table></table>';
		}
		gridDom.loadXML(gridXml);
		if (gridDom.parseError.errorCode == 0) {
			var tblNd = gridDom.selectSingleNode('//table');
			if (tblNd) {
				tblNd.setAttribute('base_href', aras.getScriptsURL());
			}
			res = aras.applyXsltFile(gridDom, aras.getScriptsURL() + '../styles/printGrid4Export.xsl');
		}
		return res;
	}

	function generateXML(gridDom, workSheetName) {
		var res = '';
		var tblNd = gridDom.selectSingleNode('//table');
		if (tblNd) {
			tblNd.setAttribute('base_href', aras.getScriptsURL());

			if (workSheetName) {
				tblNd.setAttribute('workSheet', workSheetName);
			}
		}
		var xml = ArasModules.xml;
		var xslt = xml.parseFile(aras.getScriptsURL() + '../styles/printGrid4ExportToExcel.xsl');
		return xml.transform(gridDom, xslt);
	}
};

//this method is for internal purposes only.
Aras.prototype.saveString2File = function ArasSaveString2File(contentCallback, extension, fileName) {
	var ext = extension ? extension.toLowerCase() : 'unk';
	var fileNamePrefix = fileName || 'export2unknown_type';

	var mimeType = '';
	if (ext.indexOf('excel') !== -1) {
		ext = 'xls';
		mimeType = 'application/excel';
		fileNamePrefix = this.getResource('', 'aras_object.export2excel_file_prefix');
	} else if (ext.indexOf('word') !== -1) {
		ext = 'doc';
		mimeType = 'application/msword';
		fileNamePrefix = this.getResource('', 'aras_object.export2word_file_prefix');
	}

	var blob = new Blob([contentCallback()], {type: mimeType});
	if ('msSaveBlob' in window.navigator) {
		window.navigator.msSaveBlob(blob, fileNamePrefix + '.' + ext);
		return;
	}

	var link = document.createElement('a');
	link.href = URL.createObjectURL(blob);
	link.download = fileNamePrefix + '.' + ext;
	link.setAttribute('type',  mimeType);

	var e = document.createEvent('MouseEvents');
	e.initEvent('click' ,true ,true);
	link.dispatchEvent(e);
};
// --- Export to Office section ---

Aras.prototype.EscapeSpecialChars = function Aras_EscapeSpecialChars(str) {
	if (!this.utilDoc) {
		this.utilDoc = this.createXMLDocument();
	}
	var element_t = this.utilDoc.createElement('t');
	element_t.text = str;
	var result = element_t.xml;
	return result.substr(3, result.length - 7);
};

// value returned as xpath function concat(), ie addition quotes aren't needed
Aras.prototype.EscapeXPathStringCriteria = function Aras_EscapeXPathStringCriteria(str) {
	var res = str.replace(/'/g, '\',"\'",\'');
	if (res != str) {
		return 'concat(\'' + res + '\')';
	} else {
		return '\'' + res + '\'';
	}
};

/*
//unit tests for Aras_isPropertyValueValid function
Boolean ? value is 0 or 1. (*)
Color ? must satisfy regexp /^#[a-f0-9]{6}$|^btnface$/i. (*)
Color List ? must satisfy regexp /^#[a-f0-9]{6}$|^btnface$/i. (*)
Date ? input string must represent a date in a supported format. (*)
Decimal ? must be a number. (*)
Federated ? read-only. No check.
Filter List ? string length must be not greater than 64. (*)
Float ? must be a number. (*)
Foreign ? read-only. No check.
Formatted Text ? No check.
Image ? string length must be not greater than 128. (*)
Integer ? must be an integer number. (*)
Item ? must be an item id (32 characters from [0-9A-F] set). (*)
List ? string length must be not greater than 64. (*)
MD5 ? 32 characters from [0-9A-F] set. (*)
Sequence ? read-only. No check.
String ? check if length of inputted string is not greater than maximum permissible string length.
Verify against property pattern if specified. (*)
Text ? No check.

Where (*) means: Empty value is not permissible if property is marked as required.

Property definition:
data_type - string
pattern   - string
is_required - boolean
stored_length - integer
*/
/*common tests part* /
var allDataTypes = new Array("boolean", "color", "color list", "date", "decimal", "federated", "filter list", "float", "foreign", "formatted text", "image", "integer", "item", "list", "md5", "sequence", "string", "text");
function RunTest(testDescription, testDataArr, expectedResults)
{
var failedTests = [];
for (var i=0; i<testDataArr.length; i++)
{
var testData = testDataArr[i];
var data_type = testData.propertyDef.data_type;
var expectedRes = expectedResults[data_type.replace(/ /g, "_")];

var r = Aras_isPropertyValueValid(testData.propertyDef, testData.propertyValue);

if (r !== expectedRes)
{
failedTests.push(data_type);
}
}

var resStr = (failedTests.length == 0) ? "none" : failedTests.toString();
alert(testDescription + "\n\nFailed tests: " + resStr);
}
/**/
/*empty value tests* /
var expectedRes_EmptyValue =
{
boolean: true,
color  : true,
color_list: true,
date   : true,
decimal: true,
federated: true,
filter_list: true,
float  : true,
foreign: true,
formatted_text: true,
image  : true,
integer: true,
item   : true,
list   : true,
md5    : true,
sequence: true,
string : true,
text   : true
};

var expectedRes_EmptyValueAndIsRequired =
{
boolean: false,
color  : false,
color_list: false,
date   : false,
decimal: false,
federated: true,
filter_list: false,
float  : false,
foreign: true,
formatted_text: true,
image  : false,
integer: false,
item   : false,
list   : false,
md5    : false,
sequence: true,
string : false,
text   : true
};

var testData_EmptyValueAndIsRequired = [];
var testData_EmptyValue = [];
for (var i=0; i<allDataTypes.length; i++)
{
var propertyDef = {data_type: allDataTypes[i], is_required:true};
var testData    = {propertyDef: propertyDef, propertyValue: ""};
testData_EmptyValueAndIsRequired.push(testData);

propertyDef = {data_type: allDataTypes[i], is_required:false};
testData    = {propertyDef: propertyDef, propertyValue: ""};
testData_EmptyValue.push(testData);
}

RunTest("Empty value", testData_EmptyValue, expectedRes_EmptyValue);
RunTest("Empty value and property is required", testData_EmptyValueAndIsRequired, expectedRes_EmptyValueAndIsRequired);
/**/

Aras.prototype.isInteger = function Aras_isInteger(propertyValue) {
	return (String(parseInt(propertyValue)) == propertyValue);
};

Aras.prototype.isPositiveInteger = function Aras_isPositiveInteger(propertyValue) {
	return (this.isInteger(propertyValue) && parseInt(propertyValue) > 0);
};

Aras.prototype.isNegativeInteger = function Aras_isPositiveInteger(propertyValue) {
	return (this.isInteger(propertyValue) && parseInt(propertyValue) < 0);
};

Aras.prototype.isPropertyValueValid = function Aras_isPropertyValueValid(propertyDef, propertyValue, inputLocale) {
	this.ValidationMsg = '';
	var data_type = propertyDef.data_type;
	const sohCode = new RegExp(String.fromCharCode('0x01'), 'g');
	if (typeof propertyValue === 'string' && sohCode.test(propertyValue)) {
		this.ValidationMsg = this.getResource('', 'aras_object.value_property_invalid_contains_incorrect_symbols');
	}

	if (propertyValue !== '') {
		switch (data_type) {
			case 'boolean':
				if (!propertyValue == '0' && !propertyValue == '1') {
					this.ValidationMsg = this.getResource('', 'aras_object.value_property _must_be _boolean');
				}
				break;
			case 'color':
			case 'color list':
				if (!/^#[a-f0-9]{6}$|^btnface$/i.test(propertyValue)) {
					this.ValidationMsg = this.getResource('', 'aras_object.value_property_invalid_contains_incorrect_symbols');
				}
				break;
			case 'date':
				var dateFormat = this.getDateFormatByPattern(propertyDef.pattern || 'short_date'),
					lessStrictFormat = dateFormat,
					neutralDate, dotNetPattern;

				propertyValue = typeof (propertyValue) === 'string' ? propertyValue.trim() : propertyValue;
				while (lessStrictFormat && !neutralDate) {
					dotNetPattern = this.getClippedDateFormat(lessStrictFormat) || this.getDotNetDatePattern(lessStrictFormat);
					neutralDate = this.getIomSessionContext().ConvertToNeutral(propertyValue, data_type, dotNetPattern);
					lessStrictFormat = this.getLessStrictDateFormat(lessStrictFormat);
				}

				if (typeof neutralDate !== 'string') {
					this.ValidationMsg = this.getResource('', 'aras_object.value_property_invalid_must_be_date');
				}
				break;
			case 'decimal':
				var maximumIntegerDigits;
				var hasScale = typeof propertyDef.scale != 'undefined';
				if (typeof propertyDef.precision != 'undefined') {
					maximumIntegerDigits = propertyDef.precision;

					if (hasScale) {
						maximumIntegerDigits -= propertyDef.scale;
					}
				}
				if (Number.isNaN(ArasModules.intl.number.parseFloat(propertyValue, maximumIntegerDigits))) {
					this.ValidationMsg = this.getResource('', 'aras_object.value_property_invalid_must_be_decimal', propertyDef.precision, hasScale ? propertyDef.scale : this.getResource('', 'aras_object.value_property_invalid_must_be_decimal_any'));
				}
				break;
			case 'federated':
				break;
			case 'float':
				if (Number.isNaN(ArasModules.intl.number.parseFloat(propertyValue, maximumIntegerDigits))) {
					this.ValidationMsg = this.getResource('', 'aras_object.value_property_invalid_must_be_float');
				}
				break;
			case 'foreign':
			case 'formatted text':
				break;
			case 'image':
				if (propertyValue.length > 128) {
					this.ValidationMsg = this.getResource('', 'aras_object.length_image_property_cannot_be_larger_128_symbols');
				}
				break;
			case 'integer':
				if (Number.isNaN(ArasModules.intl.number.parseInt(propertyValue))) {
					this.ValidationMsg = this.getResource('', 'aras_object.value_property_invalid_must_be_integer');
				}
				break;
			case 'item':
				if (typeof (propertyValue) == 'string' && !/^[0-9a-f]{32}$/i.test(propertyValue)) {
					this.ValidationMsg = this.getResource('', 'aras_object.value_property_invalid_must_be_item_id');
				}
				break;
			case 'md5':
				if (propertyDef.stored_length) {
					var pattern = new RegExp("^[0-9a-f]{" + propertyDef.stored_length + "}$", "i");
					if (!pattern.test(propertyValue)) {
						this.ValidationMsg = this.getResource('', 'aras_object.length_properties_value_canot_be_larger', propertyDef.stored_length);
					}
				} else if (!/^[0-9a-f]{32}$/i.test(propertyValue)) {
					this.ValidationMsg = this.getResource('', 'aras_object.value_property_invalid_must_be_md5');
				}
				break;
			case 'sequence':
				break;
			case 'filter list':
			case 'list':
			case 'ml_string':
			case 'mv_list':
			case 'string':
				if (propertyDef.stored_length < propertyValue.length) {
					this.ValidationMsg = this.getResource('', 'aras_object.length_properties_value_canot_be_larger', propertyDef.stored_length);
					break;
				}
				if (data_type == 'string' && propertyDef.pattern) {
					var re = new RegExp(propertyDef.pattern);
					if (!re.test(propertyValue)) {
						this.ValidationMsg = this.getResource('', 'aras_object.value_property_invalid_must_correspond_with_pattern', propertyDef.pattern);
						break;
					}
				}
				break;
			case 'text':
				break;
			case 'global_version':
			case 'ubigint':
				if (!/^\d{0,20}$/g.test(propertyValue)) {
					this.ValidationMsg = this.getResource('', 'aras_object.value_property_invalid_must_be_unsigned_big_integer');
				} else {
					const uBigIntMaxValue = "18446744073709551615";
					const ubiValue = bigInt(propertyValue);
					if (ubiValue.isNegative() || ubiValue.greater(uBigIntMaxValue)) {
						this.ValidationMsg = this.getResource('', 'aras_object.value_property_invalid_must_be_unsigned_big_integer');
					}
				}
				break;
			default:
				throw new Error(5, this.getResource('', 'aras_object.invalid_parameter_propertydef_data_type'));
				break;
		}
	}

	if (this.ValidationMsg != '') {
		this.ValidationMsg += ' ' + this.getResource('', 'aras_object.edit_again');
	}
	return this.ValidationMsg == '';
};

Aras.prototype.ValidationMsg = '';

Aras.prototype.showValidationMsg = function Aras_showValidationMsg(ownerWindow) {
	return this.confirm(this.ValidationMsg, ownerWindow);
};

/**
 * Indicate whether window is closed.
 * Supposition: sometimes invoking of property window.closed launch exception "Permission denied". (After applying patch KB918899)
 */
Aras.prototype.isWindowClosed = function Aras_isWindowClosed(window) {

	return this.browserHelper && this.browserHelper.isWindowClosed(window);
};

//+++ some api for classification +++
Aras.prototype.isClassPathRoot = function Aras_isClassPathRoot(class_path) {
	return '' == class_path || !class_path;
};

Aras.prototype.areClassPathsEqual = function Aras_areClassPathsEqual(class_path1, class_path2) {
	//return this.doesClassPath1StartWithClassPath2(class_path1, class_path2, true);
	return class_path1 == class_path2;
};

Aras.prototype.doesClassPath1StartWithClassPath2 = function Aras_doesClassPath1StartWithClassPath2(class_path1, class_path2) {
	if (class_path2.length > class_path1.length) {
		return false;
	}

	var class_path1Elements = class_path1.split('\/');
	var class_path2Elements = class_path2.split('\/');

	if (class_path2Elements.length > class_path1Elements.length) {
		return false;
	}

	for (var i = 0; i < class_path2Elements.length; i++) {
		if (class_path2Elements[i] != class_path1Elements[i]) {
			return false;
		}
	}

	return true;
};

/*
Aras.prototype.fireUnitTestsForSelectPropNdsByClassPath = function Aras_fireUnitTestsForSelectPropNdsByClassPath()
{
var pNms = new Array("simple classpath", "with chars to escape", "root1", "root2", "root3", "child class path", "wrong root");
//!!!before testing remove // and the second occurence of /* in the next code line
//var cps = new Array("/test/simple Classpath", "/*/
/*with \\chars\\ \" to escape<<>>[[[[]:-))))B!!!!", "", "/*", "/test", "/test/simple Classpath/its child", "/WRONG ROOT/simple Classpath");
var checkSums = new Array(4, 4, 3, 3, 3, 5, 5);//numbers of nodes returned according to class paths stored in cps array.

if (pNms.length!=cps.length || pNms.length!=checkSums.length)
{
alert("test setup is incorrect");
return;
}
var xml = "<Item type='ItemType'><name>test</name>"+
"<Relationships>"+
"<Item type='Property'>"+
"<name>"+pNms[0]+"</name>"+
"<class_path>"+cps[0]+"</class_path>"+
"</Item>"+
"<Item type='Property'>"+
"<name>"+pNms[1]+"</name>"+
"<class_path><![CDATA["+cps[1]+"]]></class_path>"+
"</Item>"+
"<Item type='Property'>"+
"<name>"+pNms[2]+"</name>"+
"<class_path>"+cps[2]+"</class_path>"+
"</Item>"+
"<Item type='Property'>"+
"<name>"+pNms[3]+"</name>"+
"<class_path>"+cps[3]+"</class_path>"+
"</Item>"+
"<Item type='Property'>"+
"<name>"+pNms[4]+"</name>"+
"<class_path>"+cps[4]+"</class_path>"+
"</Item>"+
"<Item type='Property'>"+
"<name>"+pNms[5]+"</name>"+
"<class_path>"+cps[5]+"</class_path>"+
"</Item>"+
"<Item type='Property'>"+
"<name>"+pNms[6]+"</name>"+
"<class_path>"+cps[6]+"</class_path>"+
"</Item>"+
"</Relationships></Item>"
var d = this.createXMLDocument();
d.loadXML(xml);
var itemTypeNd = d.documentElement;
var propNds;
var res = "Result:\n";
var class_path;
for (var i=0; i<cps.length; i++)
{
class_path = cps[i];
propNds = this.selectPropNdsByClassPath(class_path, itemTypeNd);
res += "class_path="+class_path + ", result="+((propNds && propNds.length==checkSums[i]) ? "true" : "false") + "\n";
}
alert(res);
}
*/

Aras.prototype.selectPropNdsByClassPath = function Aras_selectPropNdsByClassPath(class_path, itemTypeNd, excludePropsWithThisClassPath, ignoreProps2Delete) {
	if (!itemTypeNd || !itemTypeNd.xml) {
		return null;
	}

	var xp = 'Relationships/Item[@type=\'Property\']';
	if (ignoreProps2Delete) {
		xp += '[string(@action)!=\'delete\' and string(@action)!=\'purge\']';
	}
	var tmpXp = ' starts-with(' + this.EscapeXPathStringCriteria(class_path) + ', class_path)';
	if (excludePropsWithThisClassPath) {
		tmpXp = 'not(' + tmpXp + ')';
	}
	xp += '[' + tmpXp + ']';
	return itemTypeNd.selectNodes(xp);
};
//--- some api for classification ---

//+++ internal api for converting to/from neutral +++
Aras.prototype.getSessionContextLocale = function Aras_getSessionContextLocale() {
	return this.getIomSessionContext().GetLocale();
};

Aras.prototype.getIomSessionContext = function() {
	if (!this.sessionContext) {
		if (aras.getCommonPropertyValue("systemInfo_CurrentLocale")){
			this.sessionContext = this.IomInnovator.getI18NSessionContext();
		}
	}
	return this.sessionContext || this.IomInnovator.getI18NSessionContext();
};

Aras.prototype.getSessionContextLanguageCode = function Aras_getSessionContextLanguageCode() {
	return this.getIomSessionContext().GetLanguageCode();
};

Aras.prototype.getLanguageDirection = function Aras_getLanguageDirection(languageCode) {
	var direction,
		languages = this.getLanguagesResultNd(),
		currentLanguage;

	if (!languageCode) {
		languageCode = this.getSessionContextLanguageCode();
	}

	if (languageCode) {
		currentLanguage = languages.selectSingleNode('Item[@type=\'Language\' and code=\'' + languageCode + '\']');
		if (currentLanguage) {
			direction = this.getItemProperty(currentLanguage, 'direction');
		}
	}

	// default value is ltr
	if (!direction) {
		direction = 'ltr';
	}

	return direction;
};

Aras.prototype.getCorporateToLocalOffset = function Aras_getCorporateToLocalOffset() {
	var r = this.getIomSessionContext().GetCorporateToLocalOffset();
	r = parseInt(r);
	if (isNaN(r)) {
		r = 0;
	}
	return r;
};

Aras.prototype.parse2NeutralEndOfDayStr = function Aras_parse2NeutralEndOfDayStr(dtObj) {
	var yyyy = String(dtObj.getFullYear());
	var h = {};
	h.MM = String('0' + (dtObj.getMonth() + 1));
	h.dd = String('0' + dtObj.getDate());
	h.hh = String('0' + dtObj.getHours());
	h.mm = String('0' + dtObj.getMinutes());
	h.ss = String('0' + dtObj.getSeconds());
	for (var k in h) {
		h[k] = h[k].substr(h[k].length - 2);
	}
	var r = yyyy + '-' + h.MM + '-' + h.dd + 'T' + h.hh + ':' + h.mm + ':' + h.ss;
	r = this.convertToNeutral(r, 'date', 'yyyy-MM-ddTHH:mm:ss');
	yyyy = r.substr(0, 4);
	h.MM = r.substr(5, 2);
	h.dd = r.substr(8, 2);
	r = yyyy + '-' + h.MM + '-' + h.dd + 'T23:59:59';
	return r;
};

Aras.prototype.getDateFormatByPattern = function Aras_getDateFormatByPattern(pattern) {
	if (/_date/.test(pattern)) {
		return pattern;
	} else {
		var dateFormats = ['short_date', 'short_date_time', 'long_date', 'long_date_time'],
			currentFormat, dotNetPattern,
			i;

		for (i = 0; i < dateFormats.length; i++) {
			currentFormat = dateFormats[i];
			dotNetPattern = this.getDotNetDatePattern(currentFormat);
			alteredPattern = dotNetPattern.replace(/tt/g, 'a').replace(/dddd/g, 'EEEE');

			if (pattern === dotNetPattern || pattern === alteredPattern) {
				return currentFormat;
			}
		}
	}

	return undefined;
};

Aras.prototype.getClippedDateFormat = function Aras_getClippedDateFormat(dateFormat) {
	switch (dateFormat) {
		case 'long_date_time|no_ampm':
			var fullFormatString = this.getDotNetDatePattern('long_date_time');
			return fullFormatString.replace(/[a|t]/g, '').trim();
		case 'short_date_time|no_ampm':
			var fullFormatString = this.getDotNetDatePattern('short_date_time');
			return fullFormatString.replace(/[a|t]/g, '').trim();
		default: return '';
	}
};

Aras.prototype.getLessStrictDateFormat = function Aras_getLessStrictDateFormat(dateFormat) {
	switch (dateFormat) {
		case 'long_date':
			return 'short_date';
		case 'long_date_time':
			return 'long_date_time|no_ampm';
		case 'long_date_time|no_ampm':
			return 'short_date_time';
		case 'short_date_time':
			return 'short_date_time|no_ampm';
		case 'short_date_time|no_ampm':
			return 'short_date';
		default:
			return '';
	}
};


/**
 * converts localValue to neutral format if need
 */
Aras.prototype.convertToNeutral = function Aras_convertToNeutral(localValue, dataType, dotNetPattern) {
	var convertedValue;

	if (localValue && (typeof (localValue) !== 'object') && dataType) {
		switch (dataType) {
			case 'date':
				localValue = typeof (localValue) === 'string' ? localValue.trim() : localValue;
				dotNetPattern = dotNetPattern || 'short_date';
				convertedValue = this.getIomSessionContext().ConvertToNeutral(localValue, dataType, dotNetPattern);

				if (!convertedValue) {
					var dateFormat = this.getDateFormatByPattern(dotNetPattern),
						lessStrictFormat = this.getLessStrictDateFormat(dateFormat);

					while (lessStrictFormat && !convertedValue) {
						dotNetPattern = this.getClippedDateFormat(lessStrictFormat) || this.getDotNetDatePattern(lessStrictFormat);
						convertedValue = this.getIomSessionContext().ConvertToNeutral(localValue, dataType, dotNetPattern);
						lessStrictFormat = this.getLessStrictDateFormat(lessStrictFormat);
					}
				}
				break;
			default:
				convertedValue = this.getIomSessionContext().ConvertToNeutral(localValue, dataType, dotNetPattern);
				break;
		}
	}

	return convertedValue || localValue;
};

/**
 * converts val from neutral format if need
 */
Aras.prototype.convertFromNeutral = function Aras_convertFromNeutral(val, data_type, dotNetPattern4Date) {
	if (!val) {
		return val;
	}
	if (!data_type) {
		return val;
	}
	if (!dotNetPattern4Date) {
		dotNetPattern4Date = '';
	}
	if (val === null || val === undefined) {
		val = '';
	}
	if (typeof (val) == 'object') {
		return val;
	}

	var retVal = this.getIomSessionContext().ConvertFromNeutral(val, data_type, dotNetPattern4Date);
	if (!retVal) {
		retVal = val;
	}
	return retVal;
};

Aras.prototype.convertFromNeutralAllValues = function Aras_convertFromNeutralAllValues(itmNd) {
	if (itmNd && itmNd.xml) {
		var itemTypeNd = this.getItemTypeForClient(itmNd.getAttribute('type'), 'name').node;
		if (itemTypeNd) {
			var xpath = 'Relationships/Item[@type=\'Property\']';
			var propNds = itemTypeNd.selectNodes(xpath);
			for (var i = 0; i < propNds.length; i++) {
				var propNm = this.getItemProperty(propNds[i], 'name');
				var v = this.getItemProperty(itmNd, propNm);
				if (v) {
					var propDataType = this.getItemProperty(propNds[i], 'data_type');
					var datePtrn = '';
					if (propDataType == 'date') {
						datePtrn = this.getDotNetDatePattern(this.getItemProperty(propNds[i], 'pattern'));
					}
					this.setItemProperty(itmNd, propNm, this.convertFromNeutral(v, propDataType, datePtrn), false);
				}
			}
		}
	}
};

Aras.prototype.getDotNetDatePattern = function Aras_getDotNetDatePattern(innovatorDatePattern) {
	if (!innovatorDatePattern) {
		innovatorDatePattern = '';
	}
	var retVal = this.getIomSessionContext().GetUIDatePattern(innovatorDatePattern);
	return retVal;
};

Aras.prototype.getDecimalPattern = function Aras_getDecimalPattern(precision, scale) {
	var index,
		optionalDigitCharacter = '#',
		requiredDigitCharacter = '0',
		decimalSeparatorCharacter = '.',
		integralPartPattern = '',
		fractionalPartPattern = '';

	precision = (!precision || isNaN(precision)) ? 38 : precision;
	scale = (!scale || isNaN(scale)) ? 0 : scale;

	for (index = 0; index < precision - scale - 1; index++) {
		integralPartPattern += optionalDigitCharacter;
	}
	integralPartPattern += requiredDigitCharacter;

	for (index = 0; index < scale; index++) {
		fractionalPartPattern += requiredDigitCharacter;
	}

	return fractionalPartPattern ? integralPartPattern + decimalSeparatorCharacter + fractionalPartPattern : integralPartPattern;
};
//--- internal api for converting to/from neutral ---

Aras.prototype.getResource = function Aras_getResource() {
	if (arguments.length < 2) {
		return;
	}

	var solution = arguments[0];
	if (!solution) {
		solution = 'core';
	}
	solution = solution.toLowerCase();
	var key = arguments[1];
	var params2replace = [];
	for (var i = 0; i < arguments.length - 2; i++) {
		params2replace.push(arguments[i + 2]);
	}

	var Cache = this.getCacheObject();
	if (!Cache.UIResources[solution]) {
		Cache.UIResources[solution] = this.newUIResource(solution);
	}

	return Cache.UIResources[solution].getResource(key, params2replace);
};

Aras.prototype.getResources = function Aras_getResources(solution, keys) {
	var cache = this.getCacheObject();
	var res = {};

	for (var i = 0; i < keys.length; i++) {
		if (!cache.UIResources[solution]) {
			cache.UIResources[solution] = this.newUIResource(solution);
		}
		res[keys[i]] = cache.UIResources[solution].getResource(keys[i], []);
	}

	return res;
};

Aras.prototype.newUIResource = function Aras_newUIResource(solution) {
	var mainArasObj = this.getMainArasObject();

	if (mainArasObj && mainArasObj != this) {
		return mainArasObj.newUIResource(solution);
	} else {
		return (new UIResource(this, solution));
	}
};

function UIResource(parentAras, solution) {
	this.parentAras = parentAras;
	this.msgsCache = parentAras.newObject();
	var parentUrl = parentAras.getBaseURL();
	if (parentUrl.substr(parentUrl.length - 1, 1) != '/') {
		parentUrl += '/';
	}
	switch (solution) {
		case 'core':
			break;
		case 'plm':
			parentUrl += 'Solutions/PLM/';
			break;
		case 'qp':
			parentUrl += 'Solutions/QP/';
			break;
		case 'project':
			parentUrl += 'Solutions/Project/';
			break;
		default:
			parentUrl += 'Solutions/' + solution + '/';
			break;
	}
	var docUrl = parentAras.getI18NXMLResource('ui_resources.xml', parentUrl);

	var xmlhttp = parentAras.XmlHttpRequestManager.CreateRequest();
	xmlhttp.open('GET', docUrl, false);
	xmlhttp.send(null);
	this.doc = parentAras.createXMLDocument();
	this.doc.loadXML(xmlhttp.responseText);
	if (!this.doc.xml) {
		this.doc = null;
	}
}

UIResource.prototype.getResource = function UIResource_getResource(key, params) {
	key = this.parentAras.EscapeXPathStringCriteria(key);
	if (this.msgsCache[key] && (!params || params.length === 0)) {
		return this.msgsCache[key];
	}
	if (!this.doc) {
		return 'Error loading ui_resources.xml file.';
	}
	var re, val;
	if (this.msgsCache[key]) {
		val = this.msgsCache[key];
	} else {
		var nd = this.doc.selectSingleNode('/*/resource[@key=' + key + ']');
		if (!nd) {
			return 'Resource with key="' + key + '" is not found.';
		}
		val = nd.getAttribute('value');
		this.msgsCache[key] = val;
	}
	for (var i = 0; i < params.length; i++) {
		eval('re = /\\{' + i + '\\}/g');
		val = val.replace(re, params[i]);
	}

	return val;
};

Aras.prototype.getFileText = function Aras_getFileText(fileUrl) {
	require(['dojo/_base/xhr']);
	var tmp_xmlhttp = dojo.xhrGet({url: fileUrl, sync: true});
	if (tmp_xmlhttp.ioArgs.xhr.status != 404) {
		return tmp_xmlhttp.results[0];
	}
	return;
};

Aras.prototype.getLCStateLabel = function Aras_getLCStateLabel(currentStateId, soapSendCaller, callback) {
	if (!currentStateId) {
		return '';
	}
	var key = this.MetadataCache.CreateCacheKey('getCurrentState', currentStateId);
	var state = this.MetadataCache.GetItem(key);

	if (state) {
		callback(state.Content());
		return;
	}

	var self = this,
		resultHanlder = function(result) {
			var xPath = '', state = '';

			if (result[0]) {
				result = result[0];
				xPath = './id';
			} else {
				result.results.loadXML(result.getResultsBody());
				result = result.results;
				xPath = './Item/id';
			}

			state = self.getItemProperty(result, 'label');
			if (!state) {
				var idNode = result.selectSingleNode(xPath);
				state = idNode.getAttribute('keyed_name');
			}

			var item = self.IomFactory.CreateCacheableContainer(state, currentStateId);
			self.MetadataCache.SetItem(key, item);
			callback(state);
		};
	soapSendCaller = soapSendCaller || function(xmlBody, resultHanlder) {
		var result = self.soapSend('ApplyItem', xmlBody, '', false);
		resultHanlder(result);
	};

	var xmlBody = '<Item type="Life Cycle State" action="get" select="label" id="' + currentStateId + '"/>';
	soapSendCaller(xmlBody, resultHanlder);
};

Aras.prototype.arrayToMVListPropertyValue = function Aras_arrayToMVListPropertyValue(arr) {
	var tmpArr = [];
	for (var i = 0; i < arr.length; i++) {
		tmpArr.push(arr[i].replace(/,/g, '\\,'));
	}
	return tmpArr.join(',');
};

Aras.prototype.mvListPropertyValueToArray = function Aras_mvListPropertyValueToArray(val) {
	var Delimiter = ',';
	var EscapeString = '\\';
	var tmpDelim = '#';

	val = val.replace(/#/g, EscapeString + Delimiter);
	val = val.replace(/\\,/g, tmpDelim + tmpDelim);
	var tmpArr = val.split(Delimiter);

	var retArr = [];
	for (var i = 0; i < tmpArr.length; i++) {
		retArr.push(tmpArr[i].replace(/##/g, Delimiter).replace(/\\#/g, tmpDelim));
	}
	return retArr;
};

Aras.prototype.ShowContextHelp = function Aras_ShowContextHelp(itemTypeName) {
	var tophelpurl = this.getTopHelpUrl();
	if (tophelpurl) {
		if (tophelpurl.charAt(tophelpurl.length - 1) != '/') {
			tophelpurl += '/';
		}
		var currItemType = this.getItemFromServerByName('ItemType', itemTypeName, 'help_item,help_url');
		var tmpurl = tophelpurl + this.getSessionContextLanguageCode() + '/index.htm';

		tophelpurl = WebFile.Exists(tmpurl) ? tmpurl : tophelpurl + 'en/index.htm';
		var urlstring = tophelpurl;
		if (currItemType) {
			var thisHelpId = currItemType.getProperty('help_item');
			var thisHelpURL = currItemType.getProperty('help_url');
			var thisHelp = this.getItemById('Help', thisHelpId, 0);
			if (thisHelpURL != undefined && thisHelpURL != '') {
				urlstring += '#' + thisHelpURL;
			} else {
				if (thisHelpId != undefined && thisHelpId != '') {
					this.uiShowItemEx(thisHelp, undefined);
					return;
				} else {
					urlstring = tophelpurl;
				}
			}
		}
		window.open(urlstring);
	}
};

Aras.prototype.UpdateFeatureTreeIfNeed = function Aras_UpdateFeatureTreeIfNeed() {
//alert("12345678");
//	this.uiShowItemInFrameEx("USER",this.getUserID());
//	console.log(this.getLoggedUserItem());

var a = top.aras;
var aml = "<AML>" +
	" <Item type='User' action='get' select='*'>" +
	"<id>" + aras.getUserID() + "</id>" +
	" </Item>" +
	"</AML>";

var userItem = aras.applyAML(aml);
var resultDom = aras.createXMLDocument();
resultDom.loadXML(userItem);

var isNull = "";
if (resultDom.selectNodes("//first_name")[0].text == "" || resultDom.selectNodes("//first_name")[0].text == null || resultDom.selectNodes("//first_name")[0].text == undefined) {
	isNull = "Maintain user information";
}
if (resultDom.selectNodes("//is_tdc")[0].text == "TDC/OBEC") {
	if (resultDom.selectNodes("//department")[0].text == "" || resultDom.selectNodes("//department")[0].text == null || resultDom.selectNodes("//department")[0].text == undefined) {
		isNull = "Maintain user information";
	}
}else{
	if (resultDom.selectNodes("//departmentstr")[0].text == "" || resultDom.selectNodes("//departmentstr")[0].text == null || resultDom.selectNodes("//departmentstr")[0].text == undefined) {
		isNull = "Maintain user information";
	}
}
if (resultDom.selectNodes("//email")[0].text == "" || resultDom.selectNodes("//email")[0].text == null || resultDom.selectNodes("//email")[0].text == undefined) {
	isNull = "Maintain user information";
}
if (resultDom.selectNodes("//is_tdc")[0].text == "" || resultDom.selectNodes("//is_tdc")[0].text == null || resultDom.selectNodes("//is_tdc")[0].text == undefined) {
	isNull = "Maintain user information";
}
// if (resultDom.selectNodes("//last_name")[0].text == "" || resultDom.selectNodes("//last_name")[0].text == null || resultDom.selectNodes("//last_name")[0].text == undefined) {
// 	isNull = "Maintain user information";
// }
if (resultDom.selectNodes("//majordomo")[0].text == "" || resultDom.selectNodes("//majordomo")[0].text == null || resultDom.selectNodes("//majordomo")[0].text == undefined) {
	isNull = "Maintain user information";
}
if (resultDom.selectNodes("//manager")[0].text == "" || resultDom.selectNodes("//manager")[0].text == null || resultDom.selectNodes("//manager")[0].text == undefined) {
	isNull = "Maintain user information";
}
if (resultDom.selectNodes("//is_tdc")[0].text == "TDC/OBEC") {
	if (resultDom.selectNodes("//sec")[0].text == "" || resultDom.selectNodes("//sec")[0].text == null || resultDom.selectNodes("//sec")[0].text == undefined) {
		isNull = "Maintain user information";
	}
}else{
	if (resultDom.selectNodes("//secstr")[0].text == "" || resultDom.selectNodes("//secstr")[0].text == null || resultDom.selectNodes("//secstr")[0].text == undefined) {
		isNull = "Maintain user information";
	}
}
if (resultDom.selectNodes("//superintendent")[0].text == "" || resultDom.selectNodes("//superintendent")[0].text == null || resultDom.selectNodes("//superintendent")[0].text == undefined) {
	isNull = "Maintain user information";
}
// if (resultDom.selectNodes("//telephone")[0].text == "" || resultDom.selectNodes("//telephone")[0].text == null || resultDom.selectNodes("//telephone")[0].text == undefined) {
// 	isNull = "Maintain user information";
// }
// if (resultDom.selectNodes("//description")[0].text == "" || resultDom.selectNodes("//description")[0].text == null || resultDom.selectNodes("//description")[0].text == undefined) {
// 	isNull = "Maintain user information";
// }

if (isNull) {
	var dialogArguments = new Array();
	dialogArguments['aras'] = a;
	dialogArguments['item'] = resultDom.selectSingleNode('//Item');
	dialogArguments['title'] = "Maintain user information 维护用户信息";
	var options = {
		dialogWidth: 720,
		dialogHeight: 320
	};
	var self = this;
	var callbacks = {
		oncancel: function (dialog) {
			var res = dialog.result;
			if (!res) {
				alert("请维护用户信息！");
				var mainWindow = top.aras.getMainWindow();
				top.aras.modalDialogHelper.show('DefaultPopup', mainWindow.main, dialogArguments, options, '../Solutions/setUser/scripts/sf_setUserProperty.html', callbacks);
				return;
			}
			// userItem.apply("edit");
			var userEditItem = resultDom.selectSingleNode('//Item');

			var first_name = aras.getItemProperty(userEditItem, "first_name");
			var department = aras.getItemProperty(userEditItem, "department");
			var departmentstr = aras.getItemProperty(userEditItem, "departmentstr");
			var email = aras.getItemProperty(userEditItem, "email");
			var is_tdc = aras.getItemProperty(userEditItem, "is_tdc");
			var last_name = aras.getItemProperty(userEditItem, "last_name");
			var majordomo = aras.getItemProperty(userEditItem, "majordomo");
			var manager = aras.getItemProperty(userEditItem, "manager");
			var sec = aras.getItemProperty(userEditItem, "sec");
			var secstr = aras.getItemProperty(userEditItem, "secstr");
			var superintendent = aras.getItemProperty(userEditItem, "superintendent");
			var telephone = aras.getItemProperty(userEditItem, "telephone");
			var description = aras.getItemProperty(userEditItem, "description");
			
            var asdedzxc = aras.applyMethod("sgmw_setUserProperty", "<first_name><![CDATA[" + first_name + "]]></first_name><id><![CDATA[" + aras.getUserID() + "]]></id><department><![CDATA[" + department + "]]></department><departmentstr><![CDATA[" + departmentstr + "]]></departmentstr><email><![CDATA[" + email + "]]></email><is_tdc><![CDATA[" + is_tdc + "]]></is_tdc><last_name><![CDATA[" + last_name + "]]></last_name><majordomo><![CDATA[" + majordomo + "]]></majordomo><manager><![CDATA[" + manager + "]]></manager><sec><![CDATA[" + sec + "]]></sec><secstr><![CDATA[" + secstr + "]]></secstr><superintendent><![CDATA[" + superintendent + "]]></superintendent><telephone><![CDATA[" + telephone + "]]></telephone><description><![CDATA[" + description + "]]></description>");

		}
	}
	var mainWindow = top.aras.getMainWindow();
	top.aras.modalDialogHelper.show('DefaultPopup', mainWindow.main, dialogArguments, options, '../Solutions/setUser/scripts/sf_setUserProperty.html', callbacks);
	return;
}



	if (this.isAdminUser()) {
		if (this.getMainWindow().arasMainWindowInfo.isFeatureTreeExpiredResult === 'True') {
			var license = new Licensing(this);
			license.UpdateFeatureTree(function(isSuccess) {
				if (isSuccess) {
					license.showState();
				} else {
					license._showErrorPage();
				}
			});
		}
	}
};

/**
 * This function is a wrapper for IomInnovator.ConsumeLicense to handle exсeptions in case when LicenseService has returned "500" http response.
 * Our IOM controls are hosted in the main window and are shared between other windows. So, if tearoff window calls IomInnovator.ConsumeLicense inside of try catch block and exception is occured then it appears in the main window as script error and only after that will be handled by "catch" block of tearoff window.
 */
Aras.prototype.ConsumeLicense = function Aras_ConsumeLicense(featureName) {
	var mainArasObj = this.getMainArasObject();
	if (mainArasObj && mainArasObj != this) {
		return mainArasObj.ConsumeLicense(featureName);
	} else {
		var consumeLicenseResult = {
			isError: false,
			errorMessage: undefined,
			result: undefined
		};

		try {
			consumeLicenseResult.result = this.IomInnovator.ConsumeLicense(featureName);
		} catch (e) {
			consumeLicenseResult.isError = true;
			consumeLicenseResult.errorMessage = e.message;
		}
		return consumeLicenseResult;
	}
};

/**
 * @deprecated Use this.MetadataCache.CreateCacheKey()
 * @returns {array}
 */
Aras.prototype.CreateCacheKey = function Aras_CreateCacheKey() {
	var key = this.IomFactory.CreateArrayList();
	for (var i = 0; i < arguments.length; i++) {
		key.push(arguments[i]);
	}
	return key;
};

Aras.prototype.ValidateXml = function Aras_ValidateXml(schemas, xml) {
	var xmlBody = shapeXmlBody(schemas, xml);
	var url = this.getBaseURL() + '/HttpHandlers/XmlValidatorHandler.ashx';
	var xmlhttp = this.XmlHttpRequestManager.CreateRequest();
	// search in cache
	var responseInCache = this.commonProperties.validateXmlCache.filter(function(obj) {
		return obj.key === xmlBody;
	});

	if (responseInCache.length === 1) {
		return responseInCache[0].value;
	} else {
		xmlhttp.open('POST', url, false);
		xmlhttp.send(xmlBody);
		var resText = xmlhttp.responseText;
		var resDom = this.createXMLDocument();
		resDom.loadXML(resText);
		// we limit the size of the cache by 100
		if (this.commonProperties.validateXmlCache.length > 100) {
			this.commonProperties.validateXmlCache.shift();
		}
		var cacheObject = this.newObject();
		cacheObject.key = xmlBody;
		cacheObject.value = resDom;
		this.commonProperties.validateXmlCache.push(cacheObject);
		return resDom;
	}

	function shapeXmlBody(schemas, targetXml) {
		var xmlBody = [];
		xmlBody.push('<data>');
		for (var i = 0; i < schemas.length; i++) {
			var schema = schemas[i];
			xmlBody.push('<schema namespace=\'' + schema.namespace + '\' >');
			xmlBody.push('<![CDATA[');
			xmlBody.push(schema.xml);
			xmlBody.push(']]>');
			xmlBody.push('</schema>');
		}
		xmlBody.push('<targetXml>');
		xmlBody.push('<![CDATA[');
		xmlBody.push(xml);
		xmlBody.push(']]>');
		xmlBody.push('</targetXml>');
		xmlBody.push('</data>');
		return xmlBody.join('');
	}

};

Aras.prototype.getMostTopWindowWithAras = function Aras_getMostTopWindowWithAras(windowObj) {
	return TopWindowHelper.getMostTopWindowWithAras(windowObj);
};

Aras.prototype.SsrEditorWindowId = 'BB91CEC07FF24BE5945F2E5412752E8B';

/** path.js **/
function Path() {}
Path.lastException = '';

Path.combinePath = function(dirPath, fileName) {
	var result = '';

	if (this.isMac()) {
		if (this.isValidFileName(fileName)) {
			result = dirPath + '/' + fileName;
		} else {
			throw this.lastException;
		}
	} else if (this.isWindows()) {
		if (this.isValidFileName(fileName)) {
			result = dirPath + '\\' + fileName;
		} else {
			throw this.lastException;
		}
	}
	return result;
};

Path.isValidFileName = function(filename) {
	if (this.isWindows()) {
		var cannotStartWithDotRegEx = /^\./;
		if (cannotStartWithDotRegEx.test(filename)) {
			this.lastException = 'File name cannot start with dot: ' + filename;
			return false;
		}

		var winReservedNamesRegEx = /^(con|prn|aux|nul|com[0-9]|lpt[0-9]|)(\.|$)/i;
		if (winReservedNamesRegEx.test(filename)) {
			this.lastException = 'File name is reserved by OS: ' + filename;
			return false;
		}

		/*
			The following reserved characters:
			< (less than)
			> (greater than)
			: (colon)
			" (double quote)
			/ (forward slash)
			\ (backslash)
			| (vertical bar or pipe)
			? (question mark)
			* (asterisk)
		*/
		var reservedCharactersRegEx = /^[^\\/:\*\?"<>\|]{0,255}$/;
		if (!reservedCharactersRegEx.test(filename)) {
			this.lastException = 'Invalid file name for ' + navigator.platform + ' OS: ' + filename;
			return false;
		}

		return true;
	} else if (this.isMac()) {
		var fileExp = /^([^:]){1,255}$/;
		if (fileExp.test(filename)) {
			return true;
		} else {
			this.lastException = 'invalid file name for ' + navigator.platform + ' OS: ' + filename;
			return false;
		}
	}
};

Path.isMac = function() {
	/*
	Mac - Macintosh
	Win -Windows
	X11 -Unix
	*/
	var regExp = /^Mac/;
	if (regExp.test(navigator.platform)) {
		return true;
	} else {
		return false;
	}
};

Path.isWindows = function() {
	var regExp = /^Win/;
	if (regExp.test(navigator.platform)) {
		return true;
	} else {
		return false;
	}
};

Path.isMacPath = function(path) {
	var pathExp = /^(\/{1}[^:]{0,255}[^\:\/]{1})$/;
	if (pathExp.test(path)) {
		return true;
	} else {
		return false;
	}
};

Path.isWinPath = function(path) {
	var pathExp = /^[a-zA-Z]{1}:((\\[^:<>\\\/\?\*\|\"\^\s]){1}[^:<>\\\/\?\*\|\"\^]{0,255})*$/;
	if (pathExp.test(path)) {
		return true;
	} else {
		return false;
	}
};

Path.isValidFilePath = function(path) {
	if (this.isMac()) {
		if (this.isMacPath(path)) {
			return true;
		} else {
			return false;
		}
	} else if (this.isWindows()) {
		if (this.isWinPath(path)) {
			return true;
		} else {
			return false;
		}
	} else {
		return false;
	}
};

Path.getInvalidFileNameChars = function() {
	var result = [];
	if (this.isMac()) {
		result.push(':');
	} else if (this.isWindows()) {
		result.push(':');
		result.push('\\');
		result.push('\/');
		result.push('?');
		result.push('^');
		result.push('"');
		result.push('*');
		result.push('>');
		result.push('<');
		result.push('|');
	}
	return result;
};

Path.getFileName = function(filePath) {
	if (filePath) {
		var pathSeparator = Path.isWindows() ? '\\' : '\/';
		return filePath.substring(filePath.lastIndexOf(pathSeparator) + 1, filePath.length);
	}
};

Path.getDirectoryName = function(filePath) {
	if (filePath) {
		var pathSeparator = Path.isWindows() ? '\\' : '\/';
		return filePath.substring(0, filePath.lastIndexOf(pathSeparator) + 1);
	}
};

/** MetadataCache.js **/
function MetadataCache(aras) {

	var scopeVariable = {};
	scopeVariable.aras = aras;
	scopeVariable.cache = aras.IomFactory.CreateItemCache();
	scopeVariable.cacheVariable = null;
	scopeVariable.preloadDates = {};

	scopeVariable.typeInfo = {
		ItemType: {
			typeKey: '3EC33FE3B3C333333E33CF3D33AC33C3',
			getDatesMethod: 'GetItemTypesMetadata',
			getMethod: 'GetItemType'
		},
		RelationshipType: {
			typeKey: '76381576909211E296CE0B586188709B',
			getDatesMethod: 'GetRelationshipTypesMetadata',
			getMethod: 'GetRelationshipType'
		},
		Form: {
			typeKey: '2EC22FE2B2C222222E22CF2D22AC22C2',
			getDatesMethod: 'GetFormsMetadata',
			getMethod: 'GetForm'
		},
		Method: {
			typeKey: '6E02B71E7A6E4FF38A9866C27837906D',
			getDatesMethod: 'GetClientMethodsMetadata',
			getMethod: 'GetClientMethod'
		},
		GetAllClientMethodsMetadata: {
			typeKey: 'F29AC97834104075AA42EE4984AEDC68',
			getDatesMethod: 'GetAllClientMethodsMetadata',
			getMethod: 'GetAllClientMethods'
		},
		List: {
			typeKey: '4EC44FE4B4C444444E44CF4D44AC44C4',
			getDatesMethod: 'GetListsMetadata',
			getMethod: 'GetList'
		},
		Identity: {
			typeKey: '36F92EC1A0CF43C1801F50510D86FEAD',
			getDatesMethod: 'GetIdentitiesMetadata',
			getMethod: 'GetIdentity'
		},
		GetLastModifiedSearchModeDate: {
			typeKey: 'BAD4F21DBF1C41B8B14BD3060FF5E8F5',
			getDatesMethod: 'GetLastModifiedSearchModeDate',
			getMethod: 'GetSearchModes'
		},
		ConfigurableUI: {
			typeKey: '64494CAB13F846A0AD19216DBC3E1980',
			getDatesMethod: 'GetConfigurableUiMetadata',
			getMethod: 'GetConfigurableUi'
		},
		ConfigurableUIControls: {
			typeKey: '8FF238D85E7948228738B963141521AB',
			getDatesMethod: 'GetWindowsSectionControlsMetadata',
			getMethod: 'GetWindowsSectionControls'
		},
		PresentationConfiguration: {
			typeKey: 'BDE98AE974C24A759AF406C526EFD1A7',
			getDatesMethod: 'GetPresentationConfigurationMetadata',
			getMethod: 'GetPresentationConfiguration'
		},
		CommandBarSection: {
			typeKey: '7962E50B66E44BCC9BEDC3ECAE899455',
			getDatesMethod: 'GetCommandBarSectionMetadata',
			getMethod: 'GetCommandBarSection'
		},
		// note that it returns zero-filled (GU)ID if there's no cmf_ContentType for given linked_document_type
		ContentTypeByDocumentItemType: {
			typeKey: 'E76EC697E76248CC8D08FE56C1DB880B',
			getDatesMethod: 'GetContentTypeByDocumentItemTypeMetadata',
			getMethod: 'GetContentTypeByDocumentItemType'
		},
		GetAllXClassificationTreesMetadata: {
			typeKey: '8626C9253E564BDB92C54891E36BC014',
			getDatesMethod: 'GetAllXClassificationTreesMetadata',
			getMethod: 'GetAllXClassificationTrees'
		}
	};

	scopeVariable.findTypeInfoNameById = function(id) {
		var res;
		for (var prop in this.typeInfo) {
			if (this.typeInfo.hasOwnProperty(prop)) {
				if (this.typeInfo[prop].typeKey === id) {
					res = prop;
					break;
				}
			}
		}
		return res;
	};

	scopeVariable.getPreloadDate = function(name) {
		if (!this.preloadDates[name]) {
			this.updatePreloadDates();
		}
		return this.preloadDates[name];
	};

	scopeVariable._getMostTopWindowWithAras = function() {
		return window;
	};

	scopeVariable.extractDateFromCache = function(criteriaValue, criteriaType, itemType) {
		var id = criteriaType == 'id' ? criteriaValue : this.extractIdByName(criteriaValue, itemType);
		return this.extractDateById(id, itemType);
	};

	scopeVariable.extractIdByName = function(name, itemType) {
		var key = this.createCacheKey('MetadataIdsByNameInLowerCase', this.typeInfo[itemType].typeKey);
		var container = this.getItem(key);
		if (!container) {
			this.refreshMetadata(itemType);
			container = this.getItem(key);
		}
		return container ? container.content[name.toLowerCase()] : '';
	};

	scopeVariable.extractNameById = function(id, itemType) {
		var key = this.createCacheKey('MetadataNamesById', this.typeInfo[itemType].typeKey);
		var container = this.getItem(key);
		if (!container) {
			this.refreshMetadata(itemType);
			container = this.getItem(key);
		}
		return container ? container.content[id] : '';
	};

	scopeVariable.extractDateById = function(id, itemType) {
		var key = this.createCacheKey('MetadataDatesById', this.typeInfo[itemType].typeKey);
		var container = this.getItem(key);
		if (!container) {
			this.refreshMetadata(itemType);
			container = this.getItem(key);
		}
		var date = container ? container.content[id] : '';
		if (!date) {
			var currentTime = new Date();
			date = currentTime.getFullYear() + '-' + currentTime.getMonth() + '-' + currentTime.getDate() +
			'T' + currentTime.getHours() + ':' + currentTime.getMinutes() + ':' + currentTime.getSeconds() + '.00';
		}
		return date;
	};

	scopeVariable.refreshMetadata = function(itemType, async) {
		var methodName = this.typeInfo[itemType].getDatesMethod;
		var typeKey = this.typeInfo[itemType].typeKey;

		this.removeById(typeKey, true);
		var self = this;
		var requestURL = this.generateRequestURL(methodName, '', this.getPreloadDate(itemType));
		return this.sendSoapInternal(methodName, requestURL, async ? true : false).then(function(res) {
			self.refreshMetadataInternal(res, typeKey);
		});
	};

	scopeVariable.refreshMetadataInternal = function(res, typeKey) {
		if (res.getFaultCode() !== 0) {
			this.aras.AlertError(res);
			return;
		}
		const metadataItems = JSON.parse(res.getResult().text);

		const obj = metadataItems.reduce(function(res, m) {
			res.MetadataIdsByNameInLowerCase[m.name.toLowerCase()] = m.id;
			res.MetadataNamesById[m.id] = m.name;
			res.MetadataDatesById[m.id] = m.modified_on;
			return res;
		}, {
			'MetadataIdsByNameInLowerCase': {},
			'MetadataNamesById': {},
			'MetadataDatesById': {}
		});

		Object.keys(obj).forEach(function(name) {
			const key = this.createCacheKey(name, typeKey);
			const container = this.aras.IomFactory.CreateCacheableContainer(obj[name], obj[name]);
			this.setItem(key, container);
		}, this);
	};

	scopeVariable.getSoapFromServerOrFromCache = function(methodName, queryParameters) {
		var requestURL = this.generateRequestURL(methodName, queryParameters);
		var res = this.getSoapFromCache(methodName, requestURL);
		if (!res) {
			res = this.sendSoap(methodName, requestURL);
			if (res.getFaultCode() === 0) {
				this.putSoapToCache(methodName, requestURL, res);
			}
		}
		return res;
	};

	scopeVariable.getSoapFromCache = function(methodName, requestURL) {
		var key = this.createCacheKey('MetadataServiceCache', requestURL);
		var container = this.getItem(key);
		return container ? container.content : undefined;
	};

	scopeVariable.putSoapToCache = function(methodName, requestURL, content) {
		if (!sessionStorage.getItem('ArasSessionCheck')) {
			const key = this.createCacheKey('MetadataServiceCache', requestURL);
			const container = this._getMostTopWindowWithAras().aras.IomFactory.CreateCacheableContainer(content, content);
			this.setItem(key, container);
		}
	};

	scopeVariable.generateRequestURL = function(methodName, queryParameters, cacheKey) {
		function appendParameter(param, value) {
			if (param !== '') {
				param += '&';
			}
			param += value;
			return param;
		}

		queryParameters = appendParameter(queryParameters, 'database=' + this.aras.getDatabase());
		queryParameters = appendParameter(queryParameters, 'user=' + this.aras.getCurrentLoginName());
		//Language Code (not Locale!!!) is only necessary value for I18N
		queryParameters = appendParameter(queryParameters, 'lang=' + this.aras.getSessionContextLanguageCode());
		queryParameters = appendParameter(queryParameters, 'cache=' + (cacheKey ? cacheKey : '0'));
		return this._getMostTopWindowWithAras().aras.getServerBaseURL() + 'MetaData.asmx/' + methodName + (queryParameters ? '?' + queryParameters : '');
	};

	scopeVariable.sendSoap = function(methodName, requestURL) {
		var finalRetVal;
		this.sendSoapInternal(methodName, requestURL, false).then(function(res) {
			finalRetVal = res;
		});
		return finalRetVal;
	};

	scopeVariable.sendSoapAsync = function(methodName, requestURL) {
		return this.sendSoapInternal(methodName, requestURL, true);
	};

	scopeVariable.sendSoapInternal = function(methodName, requestURL, async) {
		var aras = this.aras;
		var promiseFunction = function(resolve) {
			var finalRetVal;
			ArasModules.soap('', {
				url: requestURL,
				method: methodName,
				restMethod: 'GET',
				async: async
			}).then(function(resultNode) {
				var text;
				if (resultNode.ownerDocument) {
					var doc = resultNode.ownerDocument;
					text = doc.xml || (new XMLSerializer()).serializeToString(doc);
				} else {
					text = resultNode;
				}
				finalRetVal = new SOAPResults(aras, text, false);
				resolve(finalRetVal);
			}, function(xhr) {
				finalRetVal = new SOAPResults(aras, xhr.responseText, false);
				resolve(finalRetVal);
			});
		};

		var promise;
		if (!async) {
			promise = new ArasModules.SyncPromise(promiseFunction);
		} else {
			promise = new Promise(promiseFunction);
		}
		return promise;
	};

	scopeVariable.getItemType = function(criteriaValue, criteriaName) {
		var itemType = 'ItemType';
		var id = criteriaName == 'id' ? criteriaValue : this.extractIdByName(criteriaValue, itemType);
		var date = this.extractDateById(id, itemType);
		var queryParameters = 'id=' + id + '&date=' + date;
		var methodName = this.typeInfo.ItemType.getMethod;
		var requestURL = this.generateRequestURL(methodName, queryParameters);

		var res = this.getSoapFromCache(methodName, requestURL);
		if (!res) {
			res = this.sendSoap(methodName, requestURL);
			if (res.getFaultCode() === 0) {
				this.putSoapToCache(methodName, requestURL, res);

				var rels = res.results.selectNodes(this.aras.XPathResult() + '/Item/Relationships/Item[@type="RelationshipType"]');
				for (var i = 0; i < rels.length; i++) {
					var rel = rels[i];
					var relId = this.aras.getItemProperty(rel, 'id');
					var relDate = this.extractDateById(relId, 'RelationshipType');
					var relQueryParameters = 'id=' + relId + '&date=' + relDate;
					var relRequestURL = this.generateRequestURL(this.typeInfo.RelationshipType.getMethod, relQueryParameters);
					var relRes = new SOAPResults(this.aras, '<Result>' + rel.xml + '</Result>');
					this.putSoapToCache(this.typeInfo.RelationshipType.getMethod, relRequestURL, relRes);
				}
			}
		}
		return res;
	};

	scopeVariable.stdGet = function(typeInfo, itemType, criteriaValue, criteriaName) {
		var id = criteriaName == 'id' ? criteriaValue : this.extractIdByName(criteriaValue, itemType);
		var date = this.extractDateById(id, itemType);
		var queryParameters = 'id=' + id + '&date=' + date;

		return this.getSoapFromServerOrFromCache(typeInfo.getMethod, queryParameters);
	};

	scopeVariable.getRelationshipType = function(criteriaValue, criteriaName) {
		return this.stdGet(this.typeInfo.RelationshipType, 'RelationshipType', criteriaValue, criteriaName);
	};

	scopeVariable.getForm = function(criteriaValue, criteriaName) {
		return this.stdGet(this.typeInfo.Form, 'Form', criteriaValue, criteriaName);
	};

	scopeVariable.getClientMethod = function(criteriaValue, criteriaName) {
		var methodNd = this.getClientMethodNd(criteriaValue, criteriaName);
		if (methodNd) {
			return new SOAPResults(this.aras,'<Result>' + methodNd.xml + '</Result>');
		}
		return this.stdGet(this.typeInfo.Method, 'Method', criteriaValue, criteriaName);
	};

	scopeVariable.getClientMethodNd = function(criteriaValue, criteriaName) {
		var allMethods = this.getAllClientMethods();
		var methodId;
		if (criteriaName != 'id') {
			var idsByNames = this.getItem(this.createCacheKey('MetadataClientMethodsIdsByNames', '307C85932F514F70A81B7A09376A8D6C'));
			if (!idsByNames) {
				return;
			}
			methodId = idsByNames[criteriaValue.toLowerCase()];
		} else {
			methodId = criteriaValue;
		}
		return allMethods[methodId];
	};

	scopeVariable.getAllClientMethods = function() {
		var typeKey = this.typeInfo.GetAllClientMethodsMetadata.typeKey;
		var dateMethodName = this.typeInfo.GetAllClientMethodsMetadata.getDatesMethod;
		var methodName = this.typeInfo.GetAllClientMethodsMetadata.getMethod;

		var date = this.getLastModifiedItemDateFromCache('MetadataLastModifiedClientMethodsDate', typeKey, dateMethodName);
		var requestURL = this.generateRequestURL(methodName, 'date=' + date);
		var res = this.getSoapFromCache(methodName, requestURL);
		if (!res) {
			res = this.sendSoap(methodName, requestURL);
			var methodDict = {};
			if (res.getFaultCode() === 0) {
				var nodes = res.getResult().selectNodes(this.aras.XPathResult('/Item[@type=\'Method\']'));
				if (nodes.length > 0) {
					var idsByNames = {};
					for (var i = 0; i < nodes.length; i++) {
						var id = nodes[i].getAttribute('id');
						idsByNames[nodes[i].selectSingleNode('name').text.toLowerCase()] = id;
						methodDict[id] = nodes[i];
					}
					this.putSoapToCache(methodName, requestURL, methodDict);
					var cacheKey = this.createCacheKey('MetadataClientMethodsIdsByNames', '307C85932F514F70A81B7A09376A8D6C');
					this.setItem(cacheKey, idsByNames);
				}
			}
			res = methodDict;
		}

		return res;
	};

	scopeVariable.getQueryParametersForGetCUI = function(context) {
		// date is single maximal for all CUI config, no any per id/context division
		var date = this.extractDateById('83F725B93D9840E7A4B139E40DCDA8C4', 'ConfigurableUI');
		var complexId = 'item_type_id=' + context.item_type_id + '&location_name=' + context.location_name + '&item_classification=' + context.item_classification;
		if (context.item_id) {
			complexId += '&item_id=' + context.item_id;
		}
		var queryParameters = 'id=' + escape(complexId) + '&date=' + date;

		return queryParameters;
	};

	scopeVariable.getQueryParametersForGetCUIControls = function(context) {
		// date is single maximal for all CUI config, no any per id/context division
		var date = this.extractDateById('8FF238D85E7948228738B963141521AB', 'ConfigurableUIControls');
		var complexId = 'item_type_id=' + context.item_type_id + '&location_name=' + context.location_name + '&item_classification=' + context.item_classification;
		if (context.item_id) {
			complexId += '&item_id=' + context.item_id;
		}
		var queryParameters = 'id=' + escape(complexId) + '&date=' + date;

		return queryParameters;
	};

	scopeVariable.getConfigurableUi = function(context) {
		var queryParameters = this.getQueryParametersForGetCUI(context);
		return this.getSoapFromServerOrFromCache(this.typeInfo.ConfigurableUI.getMethod, queryParameters);
	};

	scopeVariable.getConfigurableUiAsync = function(context, isJSON) {
		const queryParameters = this.getQueryParametersForGetCUI(context);
		const methodName = this.typeInfo.ConfigurableUI.getMethod;
		const requestURL = this.generateRequestURL(methodName, queryParameters);
		const res = this.getSoapFromCache(methodName, requestURL);
		if (res) {
			return Promise.resolve(res);
		}

		if (isJSON) {
			return this._getJSON(requestURL);
		}

		return this.sendSoapAsync(methodName, requestURL).then(function(result) {
			if (result.getFaultCode() === 0) {
				this.putSoapToCache(methodName, requestURL, result);
			}
			return result;
		}.bind(this));
	};
	scopeVariable.getConfigurableUIControls = function(requestParams) {
		const queryParameters = this.getQueryParametersForGetCUIControls(requestParams);
		const methodName = this.typeInfo.ConfigurableUIControls.getMethod;
		const requestURL = this.generateRequestURL(methodName, queryParameters);

		return this._getJSON(requestURL);
	};
	scopeVariable._getJSON = function(requestURL) {
		const authHeaders = this.aras.OAuthClient.getAuthorizationHeader();
		const headers = Object.assign({'Accept': 'application/json'}, authHeaders);

		return fetch(requestURL, {headers: headers, credentials: 'same-origin'})
			.then(function(res) {
				return res.json();
			});
	};
	scopeVariable.stdGetById = function(typeInfo, itemType, id) {
		var date = this.extractDateById(id, itemType);
		return this.getSoapFromServerOrFromCache(typeInfo.getMethod, 'id=' + id + '&date=' + date);
	};

	scopeVariable.getPresentationConfiguration = function(id) {
		return this.stdGetById(this.typeInfo.PresentationConfiguration, 'PresentationConfiguration', id);
	};

	scopeVariable.getCommandBarSection = function(id) {
		return this.stdGetById(this.typeInfo.CommandBarSection, 'CommandBarSection', id);
	};

	scopeVariable.getContentTypeByDocumentItemType = function(id) {
		return this.stdGetById(this.typeInfo.ContentTypeByDocumentItemType, 'ContentTypeByDocumentItemType', id);
	};

	scopeVariable.getList = function(listIds, filterListIds) {
		//listIds - list of ids for which Value type is needed
		//filterListIds - list of ids for which Filter Value type is needed
		var queryParameters; //variable for request params
		var response; //variable with response to check content
		var methodName = this.typeInfo.List.getMethod;

		var result = '<Result>';
		var i;
		//check if list isn't empty
		if (listIds.length !== 0) {
			//for each single element in collection request for metadata to service
			for (i = 0; i < listIds.length; i++) {
				queryParameters = 'id=' + listIds[i] + '&valType=value&date=' + this.extractDateById(listIds[i], 'List');
				response = this.getSoapFromServerOrFromCache(methodName, queryParameters);
				//if fault code was returned we return object with this fault
				if (response.getFaultCode() !== 0) {
					return response;
				}
				result += response.getResultsBody();
			}
		}
		if (filterListIds.length !== 0) {
			//for each single element in collection request for metadata to service
			for (i = 0; i < filterListIds.length; i++) {
				queryParameters = 'id=' + filterListIds[i] + '&valType=filtervalue&date=' + this.extractDateById(filterListIds[i], 'List');
				response = this.getSoapFromServerOrFromCache(methodName, queryParameters);
				//if fault code was returned we return object with this fault
				if (response.getFaultCode() !== 0) {
					return response;
				}
				result += response.getResultsBody();
			}
		}
		result += '</Result>';
		result = new SOAPResults(this.aras, result);
		return result;
	};

	scopeVariable.getIdentity = function(criteriaValue, criteriaName) {
		return this.stdGet(this.typeInfo.Identity, 'Identity', criteriaValue, criteriaName);
	};

	scopeVariable.getSearchModes = function() {
		var typeKey = this.typeInfo.GetLastModifiedSearchModeDate.typeKey;
		var dateMethodName = this.typeInfo.GetLastModifiedSearchModeDate.getDatesMethod;
		var methodName = this.typeInfo.GetLastModifiedSearchModeDate.getMethod;

		var date = this.getLastModifiedItemDateFromCache('MetadataLastModifiedSearchModeDate', typeKey, dateMethodName);
		var queryParameters = 'date=' + date;
		var res = this.getSoapFromServerOrFromCache(methodName, queryParameters);
		if (res.getFaultCode() !== 0) {
			this.aras.AlertError(res);
			var resIOMError = this.aras.newIOMInnovator().newError(res.getFaultString());
			return resIOMError;
		}
		return res.getResult();
	};

	scopeVariable.getAllXClassificationTrees = function() {
		var typeKey = this.typeInfo.GetAllXClassificationTreesMetadata.typeKey;
		var dateMethodName = this.typeInfo.GetAllXClassificationTreesMetadata.getDatesMethod;
		var methodName = this.typeInfo.GetAllXClassificationTreesMetadata.getMethod;

		var date = this.getLastModifiedItemDateFromCache('GetAllXClassificationTreesMetadata', typeKey, dateMethodName);
		var queryParameters = 'date=' + date;
		var res = this.getSoapFromServerOrFromCache(methodName, queryParameters);
		if (res.getFaultCode() !== 0) {
			this.aras.AlertError(res);
			var resIOMError = this.aras.newIOMInnovator().newError(res.getFaultString());
			return resIOMError;
		}
		return res.getResult();
	};

	scopeVariable.getLastModifiedItemDateFromCache = function(cacheKey, typeKey, dateMethodName) {
		var keyDateItems = this.createCacheKey(cacheKey, typeKey);
		var date = this.getItem(keyDateItems);
		if (!date) {
			date = this.getLastModifiedItemDateFromServer(dateMethodName);
			this.removeItemById(typeKey, true);
			this.setItem(keyDateItems, date);
		}
		return date;
	};

	scopeVariable.getLastModifiedItemDateFromServer = function(dateMethodName) {
		return this.getPreloadDate(dateMethodName);
	};

	scopeVariable.updatePreloadDates = function(metadataDates) {
		if (!metadataDates) {
			metadataDates = aras.getMainWindow().arasMainWindowInfo.GetAllMetadataDates;
		}

		for (var i = 0; i < metadataDates.childNodes.length; i++) {
			this.preloadDates[metadataDates.childNodes[i].nodeName] = metadataDates.childNodes[i].text;
		}

	};

	scopeVariable.deleteListDatesFromCache = function() {
		this.removeItemById(this.typeInfo.List.typeKey);
	};

	scopeVariable.deleteFormDatesFromCache = function() {
		this.removeItemById(this.typeInfo.Form.typeKey);
	};

	scopeVariable.deleteClientMethodDatesFromCache = function() {
		this.removeItemById(this.typeInfo.Method.typeKey);
	};

	scopeVariable.deleteAllClientMethodsDatesFromCache = function() {
		this.removeItemById(this.typeInfo.GetAllClientMethodsMetadata.typeKey);
	};

	scopeVariable.deleteITDatesFromCache = function() {
		this.removeItemById(this.typeInfo.ItemType.typeKey);
	};

	scopeVariable.deleteRTDatesFromCache = function() {
		this.removeItemById(this.typeInfo.RelationshipType.typeKey);
	};

	scopeVariable.deleteIdentityDatesFromCache = function() {
		this.removeItemById(this.typeInfo.Identity.typeKey);
	};

	scopeVariable.deleteConfigurableUiDatesFromCache = function() {
		this.removeItemById(this.typeInfo.ConfigurableUI.typeKey);
	};

	scopeVariable.deleteConfigurableUiControlsDatesFromCache = function() {
		this.removeItemById(this.typeInfo.ConfigurableUIControls.typeKey);
	};

	scopeVariable.deletePresentationConfigurationDatesFromCache = function() {
		this.removeItemById(this.typeInfo.PresentationConfiguration.typeKey);
	};

	scopeVariable.deleteCommandBarSectionDatesFromCache = function() {
		this.removeItemById(this.typeInfo.CommandBarSection.typeKey);
	};

	scopeVariable.deleteContentTypeByDocumentItemTypeDatesFromCache = function() {
		this.removeItemById(this.typeInfo.ContentTypeByDocumentItemType.typeKey);
	};

	scopeVariable.deleteSearchModeDatesFromCache = function() {
		this.removeItemById(this.typeInfo.GetLastModifiedSearchModeDate.typeKey);
	};

	scopeVariable.deleteXClassificationTreesDates = function() {
		this.removeItemById(this.typeInfo.GetAllXClassificationTreesMetadata.typeKey);
	};

	scopeVariable.getItem = function(key) {
		return this.cache.GetItem(key);
	};

	scopeVariable.removeById = function(id, doNotClearDate) {
		this.cache.RemoveById(id);

		if (!doNotClearDate) {
			var typeInfoName = this.findTypeInfoNameById(id);
			delete this.preloadDates[typeInfoName];
		}
	};

	scopeVariable.setItem = function(key, item) {
		this.cache.SetItem(key, item);
	};

	scopeVariable.getItemsById = function(key) {
		return this.cache.GetItemsById(key);
	};

	scopeVariable.clearCache = function() {
		this.cache.ClearCache();
		this.preloadDates = {};
		this.updatePreloadDates();
	};

	//This function accepts any number of parameters
	scopeVariable.createCacheKey = function() {
		var key = aras.IomFactory.CreateArrayList();
		for (var i = 0; i < arguments.length; i++) {
			key.add(arguments[i]);
		}
		return key;
	};

	scopeVariable.removeItemById = function(id) {
		var mainArasObj = aras.getMainArasObject();
		if (mainArasObj && mainArasObj != aras) {
			mainArasObj.MetadataCache.RemoveItemById(id);
		} else {
			this.removeById(id);
		}
	};

	return {
		GetItemType: function(criteriaValue, criteriaName) {
			return scopeVariable.getItemType(criteriaValue, criteriaName);
		},
		GetRelationshipType: function(criteriaValue, criteriaName) {
			return scopeVariable.getRelationshipType(criteriaValue, criteriaName);
		},
		GetForm: function(criteriaValue, criteriaName) {
			return scopeVariable.getForm(criteriaValue, criteriaName);
		},
		GetClientMethod: function(criteriaValue, criteriaName) {
			return scopeVariable.getClientMethod(criteriaValue, criteriaName);
		},
		GetClientMethodNd: function(criteriaValue, criteriaName) {
			return scopeVariable.getClientMethodNd(criteriaValue, criteriaName);
		},
		GetAllClientMethods: function() {
			return scopeVariable.getAllClientMethods();
		},
		GetList: function(listIds, filterListIds) {
			return scopeVariable.getList(listIds, filterListIds);
		},
		GetApplicationVersion: function() {
			var requestUrl = scopeVariable.generateRequestURL('GetApplicationVersion', '');
			return scopeVariable.sendSoap('GetApplicationVersion', requestUrl);
		},
		GetIdentity: function(criteriaValue, criteriaName) {
			return scopeVariable.getIdentity(criteriaValue, criteriaName);
		},
		GetSearchModes: function() {
			return scopeVariable.getSearchModes();
		},
		GetAllXClassificationTrees: function() {
			return scopeVariable.getAllXClassificationTrees();
		},
		GetItemTypeName: function(id) {
			return scopeVariable.extractNameById(id, 'ItemType');
		},
		GetRelationshipTypeName: function(id) {
			return scopeVariable.extractNameById(id, 'RelationshipType');
		},
		GetFormName: function(id) {
			return scopeVariable.extractNameById(id, 'Form');
		},
		GetItemTypeId: function(name) {
			return scopeVariable.extractIdByName(name, 'ItemType');
		},
		GetRelationshipTypeId: function(name) {
			return scopeVariable.extractIdByName(name, 'RelationshipType');
		},
		GetFormId: function(name) {
			return scopeVariable.extractIdByName(name, 'Form');
		},
		ExtractDateFromCache: function(criteriaValue, criteriaType, itemType) {
			return scopeVariable.extractDateFromCache(criteriaValue, criteriaType, itemType);
		},
		DeleteListDatesFromCache: function() {
			return scopeVariable.deleteListDatesFromCache();
		},
		DeleteFormDatesFromCache: function() {
			return scopeVariable.deleteFormDatesFromCache();
		},
		DeleteClientMethodDatesFromCache: function() {
			return scopeVariable.deleteClientMethodDatesFromCache();
		},
		DeleteAllClientMethodsDatesFromCache: function() {
			return scopeVariable.deleteAllClientMethodsDatesFromCache();
		},
		DeleteITDatesFromCache: function() {
			return scopeVariable.deleteITDatesFromCache();
		},
		DeleteRTDatesFromCache: function() {
			return scopeVariable.deleteRTDatesFromCache();
		},
		DeleteIdentityDatesFromCache: function() {
			return scopeVariable.deleteIdentityDatesFromCache();
		},
		DeleteConfigurableUiDatesFromCache: function() {
			return scopeVariable.deleteConfigurableUiDatesFromCache();
		},
		DeleteConfigurableUiControlsDatesFromCache: function() {
			return scopeVariable.deleteConfigurableUiControlsDatesFromCache();
		},
		DeletePresentationConfigurationDatesFromCache: function() {
			return scopeVariable.deletePresentationConfigurationDatesFromCache();
		},
		DeleteCommandBarSectionDatesFromCache: function() {
			return scopeVariable.deleteCommandBarSectionDatesFromCache();
		},
		DeleteXClassificationTreesDates: function() {
			return scopeVariable.deleteXClassificationTreesDates();
		},
		DeleteContentTypeByDocumentItemTypeDatesFromCache: function() {
			return scopeVariable.deleteContentTypeByDocumentItemTypeDatesFromCache();
		},
		DeleteSearchModeDatesFromCache: function() {
			return scopeVariable.deleteSearchModeDatesFromCache();
		},
		GetItem: function(key) {
			return scopeVariable.getItem(key);
		},
		RemoveById: function(id) {
			return scopeVariable.removeById(id);
		},
		SetItem: function(key, item) {
			return scopeVariable.setItem(key, item);
		},
		GetItemsById: function(key) {
			return scopeVariable.getItemsById(key);
		},
		ClearCache: function() {
			return scopeVariable.clearCache();
		},
		CreateCacheKey: function() {
			return scopeVariable.createCacheKey.apply(null, arguments);
		},
		RemoveItemById: function(id) {
			return scopeVariable.removeItemById(id);
		},
		GetConfigurableUi: function(context) {
			return scopeVariable.getConfigurableUi(context);
		},
		GetConfigurableUiAsync: function(context, isJSON) {
			return scopeVariable.getConfigurableUiAsync(context, isJSON);
		},
		GetConfigurableUIControls: function(context) {
			return scopeVariable.getConfigurableUIControls(context);
		},
		GetPresentationConfiguration: function(id) {
			return scopeVariable.getPresentationConfiguration(id);
		},
		GetCommandBarSection: function(id) {
			return scopeVariable.getCommandBarSection(id);
		},
		GetContentTypeByDocumentItemType: function(id) {
			///<returns>Zero-filled (GU)ID if there's no cmf_ContentType for given linked_document_type</returns>
			return scopeVariable.getContentTypeByDocumentItemType(id);
		},
		RefreshMetadata: function(itemTypeName) {
			return scopeVariable.refreshMetadata(itemTypeName, true);
		},
		UpdatePreloadDates: function(metadataDates) {
			return scopeVariable.updatePreloadDates(metadataDates);
		}
	};
}

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

/** vars_storage.js **/
function VarsStorageClass() {
	this.unknownStorage = {};
}

VarsStorageClass.prototype.getVariable = function VarsStorageClassGetVariable(varName) {
	var res = this.unknownStorage[varName];
	return res;
};

VarsStorageClass.prototype.setVariable = function VarsStorageClassSetVariable(varName, varValue) {
	if (typeof (varValue) != 'string' && varValue !== null) {
		varValue = varValue.toString();
	}
	this.unknownStorage[varName] = varValue;
};

/** Licensing.js **/
// © Copyright by Aras Corporation, 2013.

Licensing.ActionType = {
	Activate: 0,
	Update: 1,
	Deactivate: 2
};

function Licensing(aras) {
	this.arasObject = aras;
	this.actionNamespace = aras.arasService.actionNamespace;
	this.iServiceName = aras.arasService.serviceName;
	this.url = aras.arasService.serviceUrl;
	this.propgressBarImage = '../images/Progress.gif';
	this.wnd = window;
	this.error = {};
	this.state = '';

	this._getFeatureLicenseSecureId = function(featureLicenseId) {
		if (featureLicenseId) {
			var qry = this.arasObject.newIOMItem('Feature License', 'get');
			qry.setID(featureLicenseId);
			qry.setAttribute('select', 'secure_id');
			qry = qry.apply();
			if (!qry.isError() && qry.getItemCount() === 1) {
				return qry.getProperty('secure_id');
			}
		}
		return '';
	};

	this._validateActivationKey = function(activationKey) {
		if (!activationKey) {
			this.arasObject.AlertError(this.arasObject.getResource('', 'licensing.activation_key_is_empty'), '', '', this.wnd);
			return false;
		}
		return true;
	};

	this._getNonFailedDoc = function(arasObject, result) {
		if (!result) {
			this.error = {
				details: arasObject.getResource('', 'licensing.service_not_available'),
				title: arasObject.getResource('', 'licensing.service_not_available_title'),
			};
			return false;
		} else if (result.search(/<DOCTYPE/) !== -1) {
			this.error = {details: arasObject.getResource('', 'licensing.not_found')};
			return false;
		}

		var doc = arasObject.createXMLDocument();
		doc.loadXML(result);
		if (doc.selectSingleNode('//faultstring')) {
			this.error = {details: doc.selectSingleNode('//faultstring').text};
			return false;
		}
		return doc;
	};

	this._checkErrors = function(arasObject, result) {
		var doc = this._getNonFailedDoc(arasObject, result);
		if (!doc) {
			return doc;
		}
		var query = arasObject.newIOMInnovator().newItem();
		query.loadAML(doc.firstChild.text || '<Empty/>');
		var envelopeNd = query.dom.selectSingleNode('//*[local-name()=\'Envelope\']');
		if (envelopeNd) {
			query.loadAML(envelopeNd.xml);
		}
		if (query.isError()) {
			this.error = {alert: true, query: query};
			return false;
		}
		return query;
	};

	this._showErrorPage = function(win, activationKey) {
		var error = this.error;
		var params;

		this.error = null;
		var mainWindow = this.arasObject.getMainWindow();
		if (error && error.customError) {
			params = {
				aras: this.arasObject,
				subjectHide: error.subjectHide,
				errorDetails: error.details,
				title: error.title,
				dialogWidth: 365,
				dialogHeight: 140,
				content: 'Licensing/ActivateError.html'
			};
			mainWindow.ArasModules.Dialog.show('iframe', params);
		} else if (error && error.alert) {
			this.arasObject.AlertError(error.query);
		} else if (error) {
			var result = this._getRequiredServerInfo();
			if (activationKey) {
				result += '<activation_key>' + activationKey + '</activation_key>';
			}
			params = {
				title: error.title,
				aras: this.arasObject,
				result: result,
				errorDetails: error.details,
				dialogWidth: 400,
				dialogHeight: 295,
				content: 'Licensing/ServiceError.html'
			};
			mainWindow.ArasModules.Dialog.show('iframe', params);
		} else {
			return;
		}

		if (win) {
			win.close();
		}
	};

	this._callMethodOnLicensingService = function(methodName, paramName, paramValue) {
		// don't used soap because request body isn't XML
		var xhr = new XMLHttpRequest();
		var url = this.arasObject.getServerBaseURL() + 'Licensing.asmx/' + methodName;
		xhr.open('POST', url, false);

		var additionalHeaders = this.arasObject.getHttpHeadersForSoapMessage(methodName);
		Object.keys(additionalHeaders).forEach(function(header) {
			xhr.setRequestHeader(header, additionalHeaders[header]);
		});

		var body = paramName + '=' + encodeURIComponent(paramValue);
		xhr.setRequestHeader('Content-type', 'application/x-www-form-urlencoded; charset=utf-8');
		xhr.send(body);

		if (xhr.status !== 200) {
			this._errorCallback(xhr.statusText, xhr.responseText);
			return false;
		}
		return true;
	};

	this._getFrameworkLicenseKey = function() {
		var serverInfo = this._getRequiredServerInfo();
		if (serverInfo) {
			frameworkLicenseKey = serverInfo.match(/<framework_license_key[^>]*>([^<]+)<\/framework_license_key>/)[1];
			return frameworkLicenseKey ? frameworkLicenseKey : '';
		}

		return '';
	};

	this._getRequiredServerInfo = function() {
		var result;
		var self = this;
		ArasModules.soap('', {
			url: this.arasObject.getServerBaseURL() + 'Licensing.asmx/',
			appendMethodToURL: true,
			async: false,
			method: 'GetServerInfo',
			methodNm: this.actionNamespace,
			restMethod: 'POST'
		})
					.then(function(responseText) {
						result = responseText;
					}, function(rq) {
						result = self._errorCallback(rq.statusText, rq.responseText);
					});
		if (!result) { return ''; }

		var doc = this.arasObject.createXMLDocument();
		doc.loadXML(result);
		return doc.documentElement ? doc.documentElement.text : '';
	};

	this._displayFeatureRequirementsForms = function(getMetaInfoResult, activationKey, featureLicenseId, action) {
		var self = this;
		function showFeatureRequirementDialog(params) {
			var aras = params.aras;
			var container = getLicenseActionContainer(self, activationKey);
			if (container) {
				var postData = container;
				var queryParameters = '';
				queryParameters = appendParameter(queryParameters, 'actionName=' + params.action);
				queryParameters = appendParameter(queryParameters, 'activationKey=' + params.activationKey);
				var topWndAras = aras.getMostTopWindowWithAras(window).aras;
				var formUrl = 'VirtualGetLicenseForm' + (queryParameters ? '?' + queryParameters : '');
				var postUrl = topWndAras.getBaseURL() + '/Modules/aras.innovator.core.License/PostLicenseForm';
				var xmlHttp = topWndAras.XmlHttpRequestManager.CreateRequest();
				xmlHttp.open('POST', postUrl, false);
				xmlHttp.setRequestHeader('Content-Type', 'application/json; charset=utf-8');
				xmlHttp.send(
					JSON.stringify({
						actionName: params.action,
						activationKey: params.activationKey,
						postData: postData
					}));
				return formUrl;
			} else {
				//false
				return container;
			}

			function getLicenseActionContainer(context) {
				var result = false;
				var requestBody = '' +
					'<data>' +
					'<parameterData>' +
					'<version>' + aras.commonProperties.clientRevision + '</version>' +
					'</parameterData>' +
					'</data>';
				try {
					var method = 'GetLicenseActionContainer';
					var methodNm = context.actionNamespace;
					var requestResponse;
					ArasModules.soap(requestBody, {
						url: context.url,
						async: false,
						method: method,
						methodNm: methodNm,
						SOAPAction: methodNm + context.iServiceName + '/' + method,
						headers: {}
					})
						.then(function(responseText) {
							requestResponse = responseText;
						}, function(req) {
							var dialogErrorCallback = context._GenerateActivateErrorCallback(
								context.arasObject.getResource('', 'licensing.could_not_load_feature_requirements'),
								activationKey
							);
							dialogErrorCallback(req.statusText, req.responseText, req.status);
						});

					var doc = aras.createXMLDocument();
					doc.loadXML(requestResponse);
					var envelope = doc.selectSingleNode('//*[local-name()=\'Envelope\']');
					if (envelope) {
						result = envelope.text;
					}
				}
				finally {
					return result;
				}
			}

			function appendParameter(param, value) {
				if (param !== '') {
					param += '&';
				}
				param += value;
				return param;
			}
		}

		var query = this._checkErrors(this.arasObject, getMetaInfoResult);
		if (!query) {
			this._showErrorPage(null, activationKey);
			return false;
		}

		var params = this.arasObject.newObject();
		params.aras = this.arasObject;
		var formArray = [];
		var itemTypeArray = [];
		var instanceArray = [];
		var listArray = [];
		var width = 350;
		var height = 150;
		var forms = query.getItemsByXPath('/AML/Item[@type=\'Form\']');
		var formsCount = forms.getItemCount();
		if (formsCount === 0) {
			if (action !== Licensing.ActionType.Deactivate) {
				return featureLicenseId ? this.Update(featureLicenseId) : this.Activate(activationKey);
			}
			return this.Deactivate(featureLicenseId);
		} else {
			for (var i = 0; i < formsCount; i++) {
				var formItem = forms.getItemByIndex(i);

				var w = parseInt(formItem.getProperty('width'));
				var h = parseInt(formItem.getProperty('height'));
				width = w > width ? w : width;
				height = h > height ? h : height;

				formArray.push(formItem);
				listArray.push(query.getItemsByXPath('/AML/Item[@type=\'List\']'));
				itemTypeArray.push(query.getItemsByXPath('/AML/Item[@type=\'ItemType\' and name=\'' + formItem.getProperty('name') + '\']'));
				instanceArray[i] = query.getItemsByXPath('/AML/Item[@type=\'' + formItem.getProperty('name') + '\']');
			}

			height = parseInt(height) + 66;
			params.licensingObject = this;
			params.forms = formArray;
			params.itemTypes = itemTypeArray;
			params.listArray = listArray;
			params.instances = instanceArray;
			params.activationKey = activationKey;
			params.featureLicenseId = featureLicenseId;
			params.action = action;
			self = this;
			params.dialogWidth = width;
			params.dialogHeight = height;
			var formUrl = showFeatureRequirementDialog(params);
			if (formUrl) {
				params.content = formUrl;
				var mainWindow = this.arasObject.getMainWindow();
				mainWindow.ArasModules.Dialog.show('iframe', params);
			} else {
				return false;
			}
		}
		return true;
	};

	this._getMetaInfoFromArasService = function(action, activationKey, featureLicenseId) {

		var methodName;
		var callbackMethod;
		var parameterName = 'featureLicenseSecureId';
		var parameterValue = this._getFeatureLicenseSecureId(featureLicenseId);

		if (Licensing.ActionType.Activate === action) {
			parameterName = 'activationKey';
			parameterValue = activationKey;
			methodName = 'GetMetaInfoForActivate';
			callbackMethod = this._GenerateActivateErrorCallback(null, activationKey);
		} else if (Licensing.ActionType.Update === action) {
			methodName = 'GetMetaInfoForUpdate';
		} else if (Licensing.ActionType.Deactivate === action) {
			methodName = 'GetMetaInfoForDeactivate';
		}

		var metaInfoResult;
		var statusId;
		try {
			statusId = this.arasObject.showStatusMessage('status', this.arasObject.getResource('', 'licensing.request_aras'), this.propgressBarImage);

			var methodNamespace = this.actionNamespace;
			var requestBody = '<' + parameterName + '>' + parameterValue + '</' + parameterName + '>';

			ArasModules.soap(requestBody, {
				url: this.url,
				async: false,
				method: methodName,
				methodNm: methodNamespace,
				SOAPAction: methodNamespace + this.iServiceName + '/' + methodName,
				headers: {}
			})
				.then(function(responseText) {
					metaInfoResult = responseText;
				}, function(req) {
					callbackMethod(req.statusText, req.responseText, req.status);
				});
		} finally {
			this.arasObject.clearStatusMessage(statusId);
		}
		this._displayFeatureRequirementsForms(metaInfoResult, activationKey, featureLicenseId, action);
	};

	this._showInformationAboutImportedFeatureLicense = function(result, title) {

		var self = this;
		var mainWindow = this.arasObject.getMainWindow();
		mainWindow.ArasModules.Dialog.show('iframe', {
			aras: this.arasObject,
			result: result,
			title: this.arasObject.getResource('', 'licensing.success_import_title'),
			dialogWidth: 600,
			dialogHeight: 270,
			center: true,
			content: 'Licensing/SuccessMessage.html'
		});
	};

	this._showActivateFeatureDialog = function LicensingShowActivateFeatureDialog(activationKey, action, featureLicenseId) {

		var aras = this.arasObject;
		var params = this.arasObject.newObject();
		params.aras = aras;
		params.licensingObject = this;
		params.action = action;
		params.activationKey = activationKey;
		params.featureLicenseId = featureLicenseId;
		params.dialogWidth = 350;
		params.dialogHeight = 140;
		params.center = true;
		params.content = 'Licensing/ActivateFeature.html';
		switch (action || Licensing.ActionType.Activate) {
			case 0:
				params.title = aras.getResource('', 'licensing.action_type_activate');
				break;
			case 1:
				params.title = aras.getResource('', 'licensing.action_type_update');
				break;
			case 2:
				params.title = aras.getResource('', 'licensing.action_type_deactivate');
				break;
		}

		var mainWindow = aras.getMainWindow();
		mainWindow.ArasModules.Dialog.show('iframe', params);
	};

	this._getFeatureLicenseByLicenseData = function(encryptedFeatureLicense) {
		var qry = this.arasObject.newIOMItem('Feature License', 'get');
		if (encryptedFeatureLicense && encryptedFeatureLicense.length > 3999) {
			encryptedFeatureLicense = encryptedFeatureLicense.substring(0, 3999) + '%';
		}
		qry.setProperty('license_data', encryptedFeatureLicense);
		return qry.apply();
	};

	this._prepareLicenseRequestBody = function(propertyName, propertyValue, additionalData) {
		var serverInfo = this._getRequiredServerInfo();
		additionalData = additionalData ? additionalData : '<additonal_data />';
		var result = '' +
		'<' + propertyName + '>' + propertyValue + '</' + propertyName + '>' +
		'<data>' +
		'	<FeatureLicense>' +
		serverInfo +
		additionalData +
		'	</FeatureLicense>' +
		'</data>';
		return result;
	};

	this._getFeatureTreeFromInnovatorServer = function() {
		var method = 'GetFeatureTree';
		var methodNm = this.actionNamespace;
		var self = this;
		var res;

		ArasModules.soap('', {
			url: this.arasObject.getServerBaseURL() + 'Licensing.asmx/GetFeatureTree',
			async: false,
			method: method,
			methodNm: methodNm,
			SOAPAction: methodNm + this.iServiceName + '/' + method,
			headers: this.arasObject.getHttpHeadersForSoapMessage()
		})
			.then(function(result) {
				res = result;
			}, function(req) {
				self._errorCallback(req.statusText, req.responseText, req.status);
			});

		return res;
	};

	this._errorCallback = function(errorMessage, technicalMessage, stackTrace) {
		technicalMessage = !technicalMessage ? '' : technicalMessage;
		stackTrace = !stackTrace ? technicalMessage : stackTrace;
		this.arasObject.AlertError(errorMessage, technicalMessage, stackTrace);
		return false;
	};

	this._GetResponseFaultstring = function(responseText) {
		var doc = this.arasObject.createXMLDocument();
		doc.loadXML(responseText);

		var errorDetails = '';

		if (doc.selectSingleNode('//faultstring')) {
			errorDetails = doc.selectSingleNode('//faultstring').text;
		}
		return errorDetails;
	};

	this._GenerateActivateErrorCallback = function(messagePrefix, activationKey) {
		var prefix = messagePrefix;
		if (!prefix) {
			prefix = '';
		}
		return function(statusText, responseText, status) {
			if (status !== 404) {
				var errorDetails = this._GetResponseFaultstring(responseText);
				this._ShowActivateErrorDialog(prefix + errorDetails);
			}
		}.bind(this);
	};

	this._ShowActivateErrorDialog = function(errorDetails) {
		var params = this.arasObject.newObject();
		params.aras = this.arasObject;
		params.errorDetails = errorDetails;
		params.title = this.arasObject.getResource('', 'licensing.activation_error_tilte');
		params.dialogWidth = 365;
		params.dialogHeight = 160;
		params.content = 'Licensing/ActivateError.html';
		var mainWindow = this.arasObject.getMainWindow();
		mainWindow.ArasModules.Dialog.show('iframe', params);
		return false;
	};
}

Licensing.prototype.GetLicenseAgreement = function LicensingGetLicenseAgreement(activationKey) {
	var requestBody = this._prepareLicenseRequestBody('activationKey', activationKey);
	var query = false;
	var statusId = '';
	try {
		statusId = this.arasObject.showStatusMessage('status', this.arasObject.getResource('', 'licensing.request_aras'), this.propgressBarImage);

		var method = 'GetLicenseAgreement';
		var methodNm = this.actionNamespace;
		var self = this;
		var requestResponse;
		ArasModules.soap(requestBody, {
			url: this.url,
			async: false,
			method: method,
			methodNm: methodNm,
			SOAPAction: methodNm + this.iServiceName + '/' + method,
			headers: {}
		})
			.then(function(responseText) {
				requestResponse = responseText;
			}, function(req) {
				self._GenerateActivateErrorCallback(null, activationKey)(req.statusText, req.responseText, req.status);
			});

		query = this._checkErrors(this.arasObject, requestResponse);
	} finally {
		this.arasObject.clearStatusMessage(statusId);
	}
	return query;
};

Licensing.prototype.Activate = function LicensingActivate(activationKey, additionalData, additionalOptions) {
	if (!this._validateActivationKey(activationKey)) {
		return false;
	}

	var requestBody = this._prepareLicenseRequestBody('activationKey', activationKey, additionalData);
	var statusId = '';
	try {
		statusId = additionalOptions ? additionalOptions.statusId : this.arasObject.showStatusMessage('status',
		this.arasObject.getResource('', 'licensing.request_aras'), this.propgressBarImage);

		var method = 'Activate';
		var methodNm = this.actionNamespace;
		var self = this;
		var requestResponse;

		ArasModules.soap(requestBody, {
			url: this.url,
			async: false,
			method: method,
			methodNm: methodNm,
			SOAPAction: methodNm + this.iServiceName + '/' + method,
			headers: {}
		})
			.then(function(responseText) {
				requestResponse = responseText;
			}, function(req) {
				self._GenerateActivateErrorCallback(null, activationKey)(req.statusText, req.responseText, req.status);
			});

		if (!requestResponse) {
			return false;
		}

		var query = this._checkErrors(this.arasObject, requestResponse);
		if (!query) {
			this._showErrorPage(additionalOptions ? additionalOptions.win : null);
			return false;
		}

		if (additionalOptions) {
			additionalOptions.featureAction = 'activate';
		}

		return this.ImportFeatureLicense(query.getResult(), additionalOptions);
	} finally {
		this.arasObject.clearStatusMessage(statusId);
	}
};

Licensing.prototype.Update = function LicensingUpdate(featureLicenseId, additionalData, additionalOptions) {
	var featureLicenseSecureId = this._getFeatureLicenseSecureId(featureLicenseId);
	var requestBody = this._prepareLicenseRequestBody('featureLicenseSecureId', featureLicenseSecureId, additionalData);
	var statusId = '';
	try {
		statusId = additionalOptions ? additionalOptions.statusId : this.arasObject.showStatusMessage('status',
		this.arasObject.getResource('', 'licensing.request_aras'), this.propgressBarImage);

		var method = 'Update';
		var methodNm = this.actionNamespace;
		var requestResponse;

		ArasModules.soap(requestBody, {
			url: this.url,
			async: false,
			method: method,
			methodNm: methodNm,
			SOAPAction: methodNm + this.iServiceName + '/' + method,
			headers: {}
		})
			.then(function(responseText) {
				requestResponse = responseText;
			});

		var query = this._checkErrors(this.arasObject, requestResponse);
		if (!query) {
			this._showErrorPage(additionalOptions ? additionalOptions.win : null);
			return false;
		}

		if (additionalOptions) {
			additionalOptions.win.close();
		}

		var mainWindow = this.arasObject.getMainWindow();
		var self = this;
		mainWindow.ArasModules.Dialog.show('iframe', {
			aras: this.arasObject,
			featureAction: 'update',
			title: arasObject.getResource('', 'licensing.success_update_title'),
			dialogWidth: 350,
			dialogHeight: 120,
			center: true,
			content: 'Licensing/SuccessMessage.html'
		});

		return true;
	} finally {
		this.arasObject.clearStatusMessage(statusId);
	}
};

Licensing.prototype.Deactivate = function LicensingDeactivate(featureLicenseId, additionalData, additionalOptions) {
	var featureLicenseSecureId = this._getFeatureLicenseSecureId(featureLicenseId);
	var requestBody = this._prepareLicenseRequestBody('featureLicenseSecureId', featureLicenseSecureId, additionalData);
	var statusId = '';
	try {
		statusId = additionalOptions ? additionalOptions.statusId : this.arasObject.showStatusMessage('status',
		this.arasObject.getResource('', 'licensing.request_aras'), this.propgressBarImage);

		var method = 'Deactivate';
		var methodNm = this.actionNamespace;
		var requestResponse;

		ArasModules.soap(requestBody, {
			url: this.url,
			async: false,
			method: method,
			methodNm: methodNm,
			SOAPAction: methodNm + this.iServiceName + '/' + method,
			headers: {}
		})
			.then(function(responseText) {
				requestResponse = responseText;
			});

		var query = this._checkErrors(this.arasObject, requestResponse);
		if (!query) {
			this._showErrorPage(additionalOptions ? additionalOptions.win : null);
			return false;
		}

		this.arasObject.deleteItem('Feature License', featureLicenseId, true);
	} finally {
		this.arasObject.clearStatusMessage(statusId);
	}
	return true;
};

Licensing.prototype.showState = function LicensingShowState() {
	if (this.state) {
		this.arasObject.AlertSuccess(this.state, window);
		this.state = null;
	}
};

Licensing.prototype.UpdateFeatureTreeUI = function LicensingUpdateFeatureTreeUI() {
	var statusId = '';
	try {
		statusId = this.arasObject.showStatusMessage('status', this.arasObject.getResource('', 'licensing.request_aras'), this.propgressBarImage);

		if (!this.UpdateFeatureTree()) {
			this._showErrorPage();
			return false;
		}
	} finally {
		this.showState();
		this.arasObject.clearStatusMessage(statusId);
	}
	return true;
};

Licensing.prototype.UpdateFeatureTree = function LicensingUpdateFeatureTree(callback) {
	var self = this;
	var getResponse = function(responseText) {
		var arasObject = self.arasObject;
		if (!responseText) {
			self.error = {
				customError: true,
				subjectHide: true,
				details: arasObject.getResource('', 'licensing.update_feature_tree_service_not_available'),
				title: arasObject.getResource('', 'licensing.update_feature_tree_service_not_available_title')
			};
			if (callback) {
				callback();
			}
			return false;
		} else if (!self._getNonFailedDoc(arasObject, responseText)) {
			self.state = arasObject.getResource('', 'licensing.feature_tree_failed_updated_featureTree');
			if (callback) {
				callback();
			}
			return false;
		}

		var doc = arasObject.createXMLDocument();
		doc.loadXML(responseText);
		var featureTreeText = doc.documentElement ? doc.documentElement.text : '';

		var bResult = self._callMethodOnLicensingService('UpdateFeatureTree', 'encryptedFeatureTree', featureTreeText);
		bResult = !!bResult;
		self.state = bResult ? arasObject.getResource('', 'licensing.feature_tree_successfully_updated') :
		arasObject.getResource('', 'licensing.feature_tree_failed_updated_featureTree');

		if (callback) {
			callback(bResult);
		}

		return bResult;
	};

	var data = '<frameworkLicenseKey>' + this._getFrameworkLicenseKey() + '</frameworkLicenseKey>';
	var method = 'GetFeatureTree';
	var methodNm = this.actionNamespace;
	var getFeatureTreeResult;

	ArasModules.soap(data, {
		async: !!callback,
		url: this.url,
		method: method,
		methodNm: methodNm,
		SOAPAction: methodNm + this.iServiceName + '/' + method,
		headers: {}
	})
		.then(function(result) {
			if (callback) {
				getResponse(result);
			} else {
				getFeatureTreeResult = result;
			}
		}, function() {
			self.state = self.arasObject.getResource('', 'licensing.feature_tree_failed_updated_featureTree');

			if (callback) {
				callback();
			}
		});

	if (!callback) {
		return getResponse(getFeatureTreeResult);
	}
};

Licensing.prototype.ShowLicenseManagerDialog = function LicensingShowLicenseManagerDialog() {

	var params = {
		aras: this.arasObject,
		title: this.arasObject.getResource('', 'licmanager.title'),
		dialogWidth: 1000,
		dialogHeight: 420,
		resizable: true,
		center: true,
		content: 'Licensing/LicManager.html'
	};

	var mainWindow = this.arasObject.getMainWindow();
	mainWindow.ArasModules.Dialog.show('iframe', params);
};

Licensing.prototype.ActivateFeature = function LicensingActivateFeature(activationKey) {
	return this._showActivateFeatureDialog(activationKey);
};

Licensing.prototype.DeactivateFeature = function LicensingDeactivateFeature(activationKey, featureLicenseId) {
	return this._showActivateFeatureDialog(activationKey, Licensing.ActionType.Deactivate, featureLicenseId);
};

Licensing.prototype.ImportFeatureLicense = function LicensingImportFeatureLicense(featureLicenseText, additionalOptions) {
	var importFeature = function(featureLicenseText) {
		var bResult = this._callMethodOnLicensingService('ImportFeatureLicense', 'encryptedFeatureLicense', featureLicenseText);
		if (bResult) {

			if (additionalOptions) {
				additionalOptions.win.close();
			}

			var featureLicense = this._getFeatureLicenseByLicenseData(featureLicenseText);
			if (featureLicense.isError()) {
				this.arasObject.AlertError(featureLicense, this.wnd);
				return false;
			}

			var self = this;

			var params = {
				aras: this.arasObject,
				result: featureLicense,
				featureAction: additionalOptions ? additionalOptions.featureAction : '',
				dialogWidth: 350,
				dialogHeight: 190,
				center: true,
				content: 'Licensing/SuccessMessage.html'
			};
			params.title = this.arasObject.getResource('', (params.featureAction === 'update') ? 'licensing.success_update_title' : 'licensing.success_import_title');

			var mainWindow = this.arasObject.getMainWindow();
			window.setTimeout(function() {
				mainWindow.ArasModules.Dialog.show('iframe', params).promise.then();
			}.bind(this), 0);
		}
	};

	if (!featureLicenseText) {

		var mainWindow = this.arasObject.getMainWindow();
		mainWindow.ArasModules.Dialog.show('iframe', {
			aras: this.arasObject,
			title: this.arasObject.getResource('', 'licensing.import_feature_license'),
			dialogWidth: 350,
			dialogHeight: 140,
			center: true,
			content: 'Licensing/ImportLicense.html'
		}).promise.then(
			function(res) {
				if (res) {
					importFeature.bind(this)(res);
				}
			}.bind(this)

		);
	} else {
		importFeature.call(this, featureLicenseText);
	}
};

Licensing.prototype.PerformActionOverFeature = function LicensingPerformActionOverFeature(action, activationKey, featureLicenseId) {

	if (!this._validateActivationKey(activationKey)) {
		return false;
	}
	this._getMetaInfoFromArasService(action, activationKey, featureLicenseId);
};

Licensing.prototype.ViewFeatureTree = function LicensingViewFeatureTree() {

	var featureTreeXml = this._getFeatureTreeFromInnovatorServer();
	if (!featureTreeXml) {
		return;
	}
	var doc = this.arasObject.createXMLDocument();
	doc.loadXML(featureTreeXml);

	var xmlDocument = this.arasObject.createXMLDocument();
	xmlDocument.validateOnParse = true;
	xmlDocument.loadXML(doc.childNodes[doc.childNodes.length - 1].text);

	var xslt = this.arasObject.createXMLDocument();
	xslt.load(this.arasObject.getScriptsURL() + 'Licensing/FeatureTree.xsl');

	featureTreeXml = xmlDocument.transformNode(xslt);

	var params = {
		aras: this.arasObject,
		featureTreeXml: featureTreeXml,
		title: 'Aras Feature Tree',
		dialogHeight: 620,
		dialogWidth: 500,
		resizable: true,
		center: true,
		scroll: true,
		content: 'Licensing/FeatureTree.html'
	};

	var mainWindow = this.arasObject.getMainWindow();
	mainWindow.ArasModules.Dialog.show('iframe', params);
};

/** ..\BrowserCode\common\javascript\FileSystemAccess.js **/
var fileSystemAccess = {
	init: function(parentAras) {
		this.fileList = {};
		this.clientData = {};
		this.lastError = '';
		if (parentAras.vault) {
			this.associatedFileList = parentAras.vault.vault.associatedFileList;
			this.fileToMd5 = parentAras.vault.vault.fileToMd5;
		} else {
			this.associatedFileList = {};
			this.fileToMd5 = {};
		}
	},
	getFileChecksum: function(file) {
		if (typeof file === 'string') {
			var parts = file.split(/[\\\/]/);
			var fileID = parts[0];
			file = this.associatedFileList[fileID] || this.fileList[fileID];
		}

		return fileSystemAccess.fileToMd5[file.size + '.' + file.name + '.' + file.lastModified] || '';
	},
	getFileSize: function(file) {
		if (typeof file === 'string') {
			var parts = file.split(/[\\\/]/);
			var fileID = parts[0];
			return this.associatedFileList[fileID].size;
		} else {
			return file.size;
		}
	},
	sendFiles: function(strUrl) {
		const form = new FormData();

		const httpRequest = new XMLHttpRequest();
		httpRequest.open('POST', strUrl, false);

		const keys = Object.keys(this.clientData);
		for (let i = 0; i < keys.length; i++) {
			const key = keys[i];
			if (key === aras.OAuthClient.authorizationHeaderName) {
				httpRequest.setRequestHeader(key, this.clientData[key]);
				continue;
			}
			form.append(key, this.clientData[key]);
		}

		const fileIds = Object.keys(this.fileList);
		for (let i = 0; i < fileIds.length; i++) {
			const fileId = fileIds[i];
			form.append(fileId, this.fileList[fileId]);
		}

		httpRequest.send(form);

		if (httpRequest.status !== 200) {
			Object.assign(this.associatedFileList, this.fileList);
			this.lastError = 'Cannot upload file. Exception name: "WebException"; Exception message: "The remote server returned an error: ' +
				httpRequest.status + '"';
			return false;
		}
		const xml = httpRequest.responseXML;
		if (xml && xml.firstChild && xml.firstChild.firstChild) {
			const result = xml.firstChild.firstChild.firstChild;
			const isFault = (result && result.nodeName.toLowerCase() === 'soap-env:fault');
			if (isFault) {
				Object.assign(this.associatedFileList, this.fileList);
			}
		}

		this.response = httpRequest.responseText;
		return true;
	},
	sendFilesAsync: function(serverUrl) {
		const res = Object.keys(aras.vault.vault.fileList).map(function(key) {
			return aras.vault.vault.fileList[key];
		});

		const clientData = this.clientData;
		const credentials = Object.keys(clientData).reduce(function(acc, key) {
			if (key !== 'XMLdata' && key !== 'SOAPACTION') {
				acc[key] = clientData[key];
			}
			return acc;
		}, {});

		let vaultModule;
		if (window.itemTypeName === 'File' && !window.frameElement) {
			const mainWnd = aras.getMainWindow();
			vaultModule = mainWnd.ArasModules.vault;
		} else {
			vaultModule = ArasModules.vault;
		}

		vaultModule.options.serverUrl = serverUrl;
		vaultModule.options.credentials = credentials;

		const handleResult = (function(res) {
			this.response = res.xml || res.parentNode.xml;
			return true;
		}).bind(this);

		return vaultModule.send(res, clientData.XMLdata)
			.then(handleResult)
			.catch(function(res) {
				if (res instanceof Error) {
					return false;
				}
				return handleResult(res);
			});
	},
	clearClientData: function() {
		this.clientData = {};
	},
	addFileToList: function(fileID, filepath) {
		if (!filepath) {
			this.lastError = 'Filename is empty';
			return false;
		}

		if (this.associatedFileList[fileID]) {
			this.fileList[fileID] = this.associatedFileList[fileID];
		} else if (typeof filepath !== 'string') {
			if (aras.Browser.isIe()) {
				filepath.Xhr = XMLHttpRequest;
			}
			this.fileList[fileID] = filepath;
			this.associatedFileList[fileID] = filepath;
		}
		return true;
	},
	removeFileFromList: function(fileId) {
		if (this.associatedFileList[fileId]) {
			delete this.associatedFileList[fileId];
		}
		if (this.fileList[fileId]) {
			delete this.fileList[fileId];
		}
	},
	selectFile: function() {
		return ArasModules.vault.selectFile().then(function(file) {
			aras.browserHelper.toggleSpinner(document, true, 'dimmer_spinner');
			return file;
		}).then(this.calculateMd5).then(function(file) {
			aras.browserHelper.toggleSpinner(document, false, 'dimmer_spinner');
			return file;
		});
	},
	clearFileList: function() {
		this.fileList = {};
	},
	setClientData: function(name, valueRenamed) {
		this.clientData[name] = valueRenamed;
	},
	getClientData: function(name) {
		return this.clientData[name];
	},
	getResponse: function() {
		return this.response || '';
	},
	setLocalFileName: function(filename) {
		this.localFileName = filename;
	},
	downloadFile: function(strUrl) {
		var fileDownloadUrl = this.makeFileDownloadUrl(strUrl);
		window.ArasModules.vault.downloadFile(fileDownloadUrl)
			.catch(function(err) {
				var win = aras.getMostTopWindowWithAras(window);
				win.aras.AlertError('Server status: ' + err.status + '. ' + err.message);
			});
		return true;
	},
	makeFileDownloadUrl: function(strUrl) {
		var fileId = /fileID=([^&]+)/ig.exec(strUrl);
		if (!fileId) {
			return false;
		}
		fileId = fileId[1];

		var fileDownloadUrl = aras.IomInnovator.getFileUrl(fileId, aras.Enums.UrlType.SecurityToken);
		if (this.localFileName) {
			fileDownloadUrl = fileDownloadUrl.replace(/fileName=.*?(?=&|$)/, 'fileName=' + encodeURIComponent(this.localFileName));
		}

		fileDownloadUrl += '&contentDispositionAttachment=1';
		return fileDownloadUrl;
	},
	calculateMd5: function(file) {
		var md5Promise = new Promise(function(resolve, reject) {
			require(['../browsercode/common/javascript/spark-md5.js'], function(SparkMD5) {
				var fileReader = new FileReader();
				var frOnload = function(e) {
					spark.append(e.target.result);
					currentChunk++;
					if (currentChunk < chunks) {
						loadNext();
					} else {
						var md5 = spark.end();
						fileSystemAccess.fileToMd5[file.size + '.' + file.name + '.' + file.lastModified] = md5;
						resolve(file);
					}
				};
				var chunkSize = 2097152; // read in chunks of 2MB
				var chunks = Math.ceil(file.size / chunkSize);
				var currentChunk = 0;
				var spark = new SparkMD5.ArrayBuffer();
				function loadNext() {
					fileReader.onload = frOnload;
					fileReader.onerror = reject;
					var start = currentChunk * chunkSize;
					var end = Math.min(file.size,start + chunkSize);
					fileReader.readAsArrayBuffer(file.slice(start, end));
				}
				loadNext();
			});
		});

		return md5Promise;
	},
	getLastError: function() {
		return this.lastError;
	},
	readText: function(file, encoding) {
		var fileReader = new FileReader();
		return new Promise(function(resolve, reject) {
			fileReader.onload = function() {
				resolve(this.result);
			};
			fileReader.onerror = reject;
			fileReader.readAsText(file, encoding);
		});
	},
	readBase64: function(file, start, count) {
		return new Promise(function(resolve, reject) {
			var fileReader = new FileReader();
			fileReader.onload = function() {
				resolve(this.result);
			};
			fileReader.onerror = reject;
			fileReader.readAsDataURL(file.slice(start, start + count));
		});
	}
};

/** ..\BrowserCode\common\javascript\BrowserHelper.js **/
function BrowserHelper(aras, aWindow) {
	'use strict';
	this.window = aWindow;
	this.aras = aras;
}

BrowserHelper.prototype.initComponents = function() {
	var timeZoneInfo = null;

	Object.defineProperty(this, 'tzInfo', {
		get: function() {
			if (!timeZoneInfo) {
				timeZoneInfo = new this.window.TimeZonesInformation();
			}
			return timeZoneInfo;
		}
	});
};

BrowserHelper.prototype.adjustHeightTexAreaWithNullableRows = function(textArea) {
	return this.aras.Browser.isIe() ?
		textArea.offsetHeight :
		((textArea.offsetHeight - 2) / 3 + 2); // There is 3 lines in case of rows == 0
};

BrowserHelper.prototype.getNodeTranslationElement = function(srcNode, nodeName, translationXMLNsURI, lang) {
	if (this.aras.Browser.isIe()) {
		return srcNode.selectSingleNode('*[local-name()=\'' + nodeName + '\' and namespace-uri()=\'' + translationXMLNsURI + '\' and @xml:lang=\'' + lang + '\']');
	}
	var nds = srcNode.getElementsByTagNameNS(translationXMLNsURI, nodeName);
	var i;
	var resNd;
	for (i = 0; i < nds.length; i++) {
		if (nds[i].parentNode == srcNode && nds[i].getAttribute('xml:lang') === lang) {
			resNd = nds[i];
			break;
		}
	}
	return resNd;
};

BrowserHelper.prototype.createTranslationNode = function(srcNode, nodeName, translationXMLNsURI, translationXMLNdPrefix) {
	if (srcNode.ownerDocument.createElementNS) {
		return srcNode.ownerDocument.createElementNS(translationXMLNsURI, translationXMLNdPrefix + ':' + nodeName);
	}
	var resNd = srcNode.ownerDocument.createNode(1, translationXMLNdPrefix + ':' + nodeName, translationXMLNsURI);
	resNd.setAttribute('xmlns:' + translationXMLNdPrefix, translationXMLNsURI);
	return resNd;
};

BrowserHelper.prototype.getTextContentPropertyName = function() {
	return 'textContent';
};

BrowserHelper.prototype.getHeightDiffBetweenTearOffAndMainWindow = function() {
	//Height of Title Bar in Main window is less than in Tear-Off window
	return this.aras.Browser.isIe() ? 0 : 8;
};

BrowserHelper.prototype.isWindowClosed = function(window) {
	var res = false;
	try {
		res = window.closed;
	}
	catch (e) {
		//"Permission denied."
		// "-2146823281" - "Object expected" - this error sometimes generates by MS edge, when window is closed and reference is corrupted
		if (e.number != -2146828218 && e.number != -2146823281) {
			throw e;
		} else {
			res = true;
		}
	}
	return res;
};

/***
 * Move window to specified coordinates
 * @param aWindow target window to move
 * @param x
 * @param y
 */
BrowserHelper.prototype.moveWindowTo = function(aWindow, x, y) {
	if (!this.aras.Browser.isEdge()) {
		aWindow.moveTo(x, y);
	}
};

/***
 * Resize window to specified measurements
 * @param aWindow window to resize
 * @param width
 * @param height
 */
BrowserHelper.prototype.resizeWindowTo = function(aWindow, width, height) {
	if (this.aras.Browser.isIe() && aWindow.dialogArguments) {
		//some dialog shown with a call to showModalDialog or showModelessDialog method
		//window.resizeTo still doesn't work for dialogs in IE. Tested in IE 9 - IE 11.
		var frameWidth = aWindow.outerWidth - aWindow.innerWidth;
		var frameHeight = aWindow.outerHeight - aWindow.innerHeight;
		//according to MSDN dialogHeight property returns the height of the content area and doesn't include the height of the frame.
		//http://msdn.microsoft.com/en-us/library/ie/ms533724%28v=vs.85%29.aspx
		aWindow.dialogHeight = (height - frameHeight) + 'px';
		aWindow.dialogWidth = (width - frameWidth) + 'px';
	} else if (!this.aras.Browser.isEdge()) {
		//regular window
		aWindow.resizeTo(width, height);
	}
};

/***
 * Set focus to specified window
 * @param aWindow Window to focus
 */
BrowserHelper.prototype.setFocus = function(aWindow) {
	// window.focus is not working in chrome for parent window.
	// We need use window.open with empty url as 1-st argument and name of exits window as 2-nd argument.
	if (aras.Browser.isCh() && aWindow.opener && !aWindow.frameElement) {
		aWindow.opener.open('', aWindow.name);
	}
	//setTimeout to fix window.focus in Mozilla Firefox
	setTimeout(function() { aWindow.focus(); }, 0);
};

BrowserHelper.prototype.lockNewWindowOpen = function(aras, lockFlag) {
	if (this.aras.Browser.isIe()) {
		aras.commonProperties.lockNewWindowOpen = lockFlag;
	}
};

BrowserHelper.prototype.newWindowCanBeOpened = function(aras) {
	return !aras.commonProperties.lockNewWindowOpen;
};

BrowserHelper.prototype.fixSizeOnModalDialogResize = function(modalDialogWin, idsToResizeWidth, idsToResizeHeight, fixBody, cb) {
	if (this.aras.Browser.isIe()) {
		modalDialogWin.addEventListener('resize', function() {
			var i;
			var doc = modalDialogWin.document;
			var w = doc.documentElement.clientWidth;
			var h = doc.documentElement.clientHeight;
			var oldw = modalDialogWin['BrowserHelper_oldClientWidth'];
			var oldh = modalDialogWin['BrowserHelper_oldClientHeight'];

			if (w != oldw) {
				if (idsToResizeWidth) {
					idsToResizeWidth = typeof idsToResizeWidth === 'string' ? [idsToResizeWidth] : idsToResizeWidth;
					for (i = 0; i < idsToResizeWidth.length; i++) {
						doc.getElementById(idsToResizeWidth[i]).style.width = w + 'px';
					}
				}

				if (fixBody) {
					doc.body.width = w + 'px';
				}

				modalDialogWin['BrowserHelper_oldClientWidth'] = w;
			}

			if (idsToResizeHeight && h != oldh) {
				if (idsToResizeHeight) {
					idsToResizeHeight = typeof idsToResizeHeight === 'string' ? [idsToResizeHeight] : idsToResizeHeight;
					for (i = 0; i < idsToResizeHeight.length; i++) {
						doc.getElementById(idsToResizeHeight[i]).style.height = h + 'px';
					}
				}

				if (fixBody) {
					doc.body.height = h + 'px';
				}

				modalDialogWin['BrowserHelper_oldClientHeight'] = h;
			}

			if (cb) {
				cb({'old': {w: oldw, h: oldh}, 'new': {w: w, h: h}});
			}
		});
	}
};

BrowserHelper.prototype.adjustGridSize = function(aWindow, handler, asFunc) {
	if (this.aras.Browser.isIe()) {
		if (asFunc) {
			aWindow.onresize = handler;
		} else {
			aWindow.addEventListener('resize', handler, false);
		}
		handler();
	}
};

/**
 * Turning on/off class in "spinner" element (classList is required)
 *
 * @param {HTMLElement|Document} context - current container object
 * @param {string} state - turn on/off spinner
 * @param {string} [spinnerId] - id attribute of spinner element
 * @return {boolean} spinner found or no
 */
BrowserHelper.prototype.toggleSpinner = function(context, state, spinnerId) {
	spinnerId = spinnerId || 'dimmer_spinner';

	var spinnerEl = (context.ownerDocument || context).getElementById(spinnerId);

	if (!spinnerEl) {
		return false;
	}

	spinnerEl.classList.toggle('aras-hide', !state);
	return true;
};

// +++++++ Methods for generating XSLT stylesheets for Grids
BrowserHelper.prototype.addXSLTCssFunctions = function(container) {
	container.push('<xsl:template name="initItemCSS">\n');
	container.push('	<xsl:param name="css"/>\n');
	container.push('	<xsl:param name="fed_css"/>\n');
	container.push('	<xsl:value-of select="translate(concat($css, $fed_css), \'&#x20;&#x9;&#xD;&#xA;\', \'\')"/>\n');
	container.push('</xsl:template>\n');

	container.push('<xsl:template name="getPropertyStyleEx">\n');
	container.push('	<xsl:param name="css"/>\n');
	container.push('	<xsl:param name="propName"/>\n');
	container.push('	<xsl:text>;</xsl:text>\n');
	container.push('	<xsl:variable name="delimiter" select="concat(\'.\', $propName, \'{\')"/>\n');
	container.push('	<xsl:if test="string-length(substring-after($css, $delimiter))">\n');
	container.push('		<xsl:variable name="resCss" select="substring-before(substring-after($css, $delimiter), \'}\')"/>\n');
	container.push('		<xsl:value-of select="$resCss"/>\n');
	container.push('		<xsl:if test="substring($resCss, string-length($resCss)) != \';\'">\n');
	container.push('			<xsl:text>;</xsl:text>\n');
	container.push('		</xsl:if>\n');
	container.push('		<xsl:call-template name="getPropertyStyleEx">\n');
	container.push('			<xsl:with-param name="css" select="substring-after($css, $delimiter)"/>\n');
	container.push('			<xsl:with-param name="propName" select="$propName"/>\n');
	container.push('		</xsl:call-template>\n');
	container.push('	</xsl:if>\n');
	container.push('</xsl:template>\n');
};

BrowserHelper.prototype.addXSLTSpecialNamespaces = function(container) {};
BrowserHelper.prototype.addXSLTInitItemCSSCall = function(container, cssValue, fedCssValue) {
	container.push('<xsl:call-template name="initItemCSS">\n');
	container.push('	<xsl:with-param name="css" select="' + cssValue + '"/>\n');
	container.push('	<xsl:with-param name="fed_css" select="' + fedCssValue + '"/>\n');
	container.push('</xsl:call-template>\n');
};

BrowserHelper.prototype.addXSLTGetPropertyStyleExCall = function(container, nameCSS, cellCSSVariableName1, name) {
	container.push('<xsl:variable name="' + nameCSS + '" >\n');
	container.push('	<xsl:call-template name="getPropertyStyleEx">\n');
	container.push('		<xsl:with-param name="css" select="string($' + cellCSSVariableName1 + ')" />\n');
	container.push('		<xsl:with-param name="propName" >' + name + '</xsl:with-param>\n');
	container.push('	</xsl:call-template>\n');
	container.push('</xsl:variable>\n');
};
// ------- Methods for generating XSLT stylesheets for Grids

BrowserHelper.prototype.escapeUrl = function(url) {
	//after xslt transformation of the data for grid in FF need to escape the url on the pictures src
	if (this.aras.Browser.isFf()) {
		return url.replace(/&/g, '&amp;');
	} else {
		return url;
	}
};

//IE does not properly set the focus in input fields in the new iframes
//We programmatically set the focus on the input field, and then remove the focus
//then IE will be able to operate normally with all input fields.
BrowserHelper.prototype.restoreFocusForIE = function(window) {
	if (this.aras.Browser.isIe()) {
		var document = window.document;
		var inputTMP = document.createElement('INPUT');
		inputTMP.setAttribute('type', 'text');
		inputTMP.style.position = 'absolute';
		inputTMP.style.top = '-1000px';
		document.body.appendChild(inputTMP);
		inputTMP.focus();
		document.body.focus();
		document.body.removeChild(inputTMP);
	}
};

/** TimeZonesInformation.js **/
function TimeZonesInformation() {
	this.cacheOlsonTzName = {};
}

/***
 * @param winTzName Name of windows time zone
 * @returns {*} Olson time zone name by windows time zone
 */
TimeZonesInformation.prototype.getOlsonTimeZoneName = function GetOlsonTimeZoneName(winTzName) {
	if (this.cacheOlsonTzName[winTzName]) {
		return this.cacheOlsonTzName[winTzName];
	}

	var xmlHttp = new XMLHttpRequest();
	xmlHttp.open('GET', aras.getBaseURL() + '/TimeZone/GetOlsonTimeZoneName?windowsTimeZoneName=' + winTzName, false);
	xmlHttp.send();
	if (xmlHttp.status == 404) {
		aras.AlertError('Could not found timeZone: ' + winTzName);
		return;
	}

	this.cacheOlsonTzName[winTzName] = xmlHttp.responseText;
	return this.cacheOlsonTzName[winTzName];
};

/***
 * @param date Date with respect to which is calculated offset
 * @param winTzName Name of windows time zone
 * @returns {*} Time zone offset using olson time zone database
 */
TimeZonesInformation.prototype.getTimeZoneOffset = function TimeZonesInformationGetTimeZoneOffset(date, winTzName) {
	// Get olson time zone name by windows time zone name
	var olsonTzName = this.getOlsonTimeZoneName(winTzName);
	dojo.require('Aras.Client.Controls.Experimental.TimeZoneInfo');
	var tzInfo = Aras.Client.Controls.Experimental.TimeZoneInfo.getTzInfo(date, olsonTzName);
	return tzInfo.tzOffset;
};

/***
 * @returns {*} Timezone name in windows format
 */
TimeZonesInformation.prototype.getTimeZoneLabel = function() {
	var getZoneNameFromDateString = function(str) {
		if (!str || (str && (str.indexOf('(') === -1 || str.indexOf(')') === -1))) {
			return;
		}
		var regexp1 = /.*?\((.*).*/;
		str = regexp1.exec(str)[1];
		if (!str) {
			return;
		}
		var regexp2 = /(.*)\)/;
		str = regexp2.exec(str)[1];

		if (str) {
			return str;
		}
	};
	var timeZoneName;
	if (aras.Browser.isIe() && aras.Browser.OSName === 'Windows') {
		var dateString = (new Date()).toString();
		timeZoneName = getZoneNameFromDateString(dateString);
	}

	if (!timeZoneName) {
		timeZoneName = jstz.determine().name();
	}

	return timeZoneName || '';
};

TimeZonesInformation.prototype.getWindowsTimeZoneNames = function(tzLabel) {
	var inputType = tzLabel.indexOf('/') > 0 ? 'iana' : 'windows';
	var localTime = (new Date()).toISOString();
	var localTimeOffset = (-1 * (new Date()).getTimezoneOffset()).toString();

	var url = aras.getBaseURL() + '/TimeZone/GetTimezoneNames?tzlabel=' +
		encodeURIComponent(tzLabel) + '&inputType=' + encodeURIComponent(inputType) +
		'&localTime=' + encodeURIComponent(localTime) +
		'&offsetBetweenLocalTimeAndUTCTime=' + encodeURIComponent(localTimeOffset);
	var xmlHttp = new XMLHttpRequest();
	xmlHttp.open('GET', url, false);
	xmlHttp.send();
	if (xmlHttp.status !== 200) {
		aras.AlertError('Could not found timeZone: ' + tzLabel);
		return [];
	}

	return JSON.parse(xmlHttp.responseText).map(function(tz) {return tz.id;});
};

TimeZonesInformation.prototype.setTimeZoneNameInLocalStorage = function(tzLabel, tzName) {
	var tzOffset = -1 * (new Date()).getTimezoneOffset();
	var timeZones = {};
	timeZones[tzOffset + tzLabel] = tzName;
	localStorage.setItem('timeZone', JSON.stringify(timeZones));
};

TimeZonesInformation.prototype.getTimeZoneNameFromLocalStorage = function(tzLabel) {
	var tzOffset = -1 * (new Date()).getTimezoneOffset();
	var timeZones = JSON.parse(localStorage.getItem('timeZone'));
	if (timeZones && timeZones.hasOwnProperty(tzOffset + tzLabel)) {
		return timeZones[tzOffset + tzLabel];
	}
};

/** md5.js **/
/*
 * A JavaScript implementation of the RSA Data Security, Inc. MD5 Message
 * Digest Algorithm, as defined in RFC 1321.
 * Version 2.1 Copyright (C) Paul Johnston 1999 - 2002.
 * Other contributors: Greg Holt, Andrew Kepert, Ydnar, Lostinet
 * Distributed under the BSD License
 * See http://pajhome.org.uk/crypt/md5 for more info.
 */

/*
* Configurable variables. You may need to tweak these to be compatible with
* the server-side, but the defaults work in most cases.
*/
var hexcase = 0;	/* hex output format. 0 - lowercase; 1 - uppercase        */
var b64pad = '';	/* base-64 pad character. "=" for strict RFC compliance   */
var chrsz = 8;		/* bits per input character. 8 - ASCII; 16 - Unicode      */

/*
* These are the functions you'll usually want to call
* They take string arguments and return either hex or base-64 encoded strings
*/
function hexMd5(s) { return binl2hex(coreMd5(str2binl(s), s.length * chrsz)); }
function b64Md5(s) { return binl2b64(coreMd5(str2binl(s), s.length * chrsz)); }
function strMd5(s) { return binl2str(coreMd5(str2binl(s), s.length * chrsz)); }
function hexHmacMd5(key, data) { return binl2hex(coreHmacMd5(key, data)); }
function b64HmacMd5(key, data) { return binl2b64(coreHmacMd5(key, data)); }
function strHmacMd5(key, data) { return binl2str(coreHmacMd5(key, data)); }

/*
* Perform a simple self-test to see if the VM is working
*/
function md5VmTest() {
	return hexMd5('abc') == '900150983cd24fb0d6963f7d28e17f72';
}

/*
* Call hexMd5, adding new param (compatibility with older version)
*/
function calcMD5(str) {
	if (!str) {
		return '';
	}
	return hexMd5(str);
}

/*
* Calculate the MD5 of an array of little-endian words, and a bit length
*/
function coreMd5(x, len) {
	/* append padding */
	x[len >> 5] |= 0x80 << ((len) % 32);
	x[(((len + 64) >>> 9) << 4) + 14] = len;

	var a = 1732584193;
	var b = -271733879;
	var c = -1732584194;
	var d = 271733878;

	for (var i = 0; i < x.length; i += 16) {
		var olda = a;
		var oldb = b;
		var oldc = c;
		var oldd = d;

		a = md5ff(a, b, c, d, x[i + 0], 7, -680876936);
		d = md5ff(d, a, b, c, x[i + 1], 12, -389564586);
		c = md5ff(c, d, a, b, x[i + 2], 17, 606105819);
		b = md5ff(b, c, d, a, x[i + 3], 22, -1044525330);
		a = md5ff(a, b, c, d, x[i + 4], 7, -176418897);
		d = md5ff(d, a, b, c, x[i + 5], 12, 1200080426);
		c = md5ff(c, d, a, b, x[i + 6], 17, -1473231341);
		b = md5ff(b, c, d, a, x[i + 7], 22, -45705983);
		a = md5ff(a, b, c, d, x[i + 8], 7, 1770035416);
		d = md5ff(d, a, b, c, x[i + 9], 12, -1958414417);
		c = md5ff(c, d, a, b, x[i + 10], 17, -42063);
		b = md5ff(b, c, d, a, x[i + 11], 22, -1990404162);
		a = md5ff(a, b, c, d, x[i + 12], 7, 1804603682);
		d = md5ff(d, a, b, c, x[i + 13], 12, -40341101);
		c = md5ff(c, d, a, b, x[i + 14], 17, -1502002290);
		b = md5ff(b, c, d, a, x[i + 15], 22, 1236535329);

		a = md5gg(a, b, c, d, x[i + 1], 5, -165796510);
		d = md5gg(d, a, b, c, x[i + 6], 9, -1069501632);
		c = md5gg(c, d, a, b, x[i + 11], 14, 643717713);
		b = md5gg(b, c, d, a, x[i + 0], 20, -373897302);
		a = md5gg(a, b, c, d, x[i + 5], 5, -701558691);
		d = md5gg(d, a, b, c, x[i + 10], 9, 38016083);
		c = md5gg(c, d, a, b, x[i + 15], 14, -660478335);
		b = md5gg(b, c, d, a, x[i + 4], 20, -405537848);
		a = md5gg(a, b, c, d, x[i + 9], 5, 568446438);
		d = md5gg(d, a, b, c, x[i + 14], 9, -1019803690);
		c = md5gg(c, d, a, b, x[i + 3], 14, -187363961);
		b = md5gg(b, c, d, a, x[i + 8], 20, 1163531501);
		a = md5gg(a, b, c, d, x[i + 13], 5, -1444681467);
		d = md5gg(d, a, b, c, x[i + 2], 9, -51403784);
		c = md5gg(c, d, a, b, x[i + 7], 14, 1735328473);
		b = md5gg(b, c, d, a, x[i + 12], 20, -1926607734);

		a = md5hh(a, b, c, d, x[i + 5], 4, -378558);
		d = md5hh(d, a, b, c, x[i + 8], 11, -2022574463);
		c = md5hh(c, d, a, b, x[i + 11], 16, 1839030562);
		b = md5hh(b, c, d, a, x[i + 14], 23, -35309556);
		a = md5hh(a, b, c, d, x[i + 1], 4, -1530992060);
		d = md5hh(d, a, b, c, x[i + 4], 11, 1272893353);
		c = md5hh(c, d, a, b, x[i + 7], 16, -155497632);
		b = md5hh(b, c, d, a, x[i + 10], 23, -1094730640);
		a = md5hh(a, b, c, d, x[i + 13], 4, 681279174);
		d = md5hh(d, a, b, c, x[i + 0], 11, -358537222);
		c = md5hh(c, d, a, b, x[i + 3], 16, -722521979);
		b = md5hh(b, c, d, a, x[i + 6], 23, 76029189);
		a = md5hh(a, b, c, d, x[i + 9], 4, -640364487);
		d = md5hh(d, a, b, c, x[i + 12], 11, -421815835);
		c = md5hh(c, d, a, b, x[i + 15], 16, 530742520);
		b = md5hh(b, c, d, a, x[i + 2], 23, -995338651);

		a = md5ii(a, b, c, d, x[i + 0], 6, -198630844);
		d = md5ii(d, a, b, c, x[i + 7], 10, 1126891415);
		c = md5ii(c, d, a, b, x[i + 14], 15, -1416354905);
		b = md5ii(b, c, d, a, x[i + 5], 21, -57434055);
		a = md5ii(a, b, c, d, x[i + 12], 6, 1700485571);
		d = md5ii(d, a, b, c, x[i + 3], 10, -1894986606);
		c = md5ii(c, d, a, b, x[i + 10], 15, -1051523);
		b = md5ii(b, c, d, a, x[i + 1], 21, -2054922799);
		a = md5ii(a, b, c, d, x[i + 8], 6, 1873313359);
		d = md5ii(d, a, b, c, x[i + 15], 10, -30611744);
		c = md5ii(c, d, a, b, x[i + 6], 15, -1560198380);
		b = md5ii(b, c, d, a, x[i + 13], 21, 1309151649);
		a = md5ii(a, b, c, d, x[i + 4], 6, -145523070);
		d = md5ii(d, a, b, c, x[i + 11], 10, -1120210379);
		c = md5ii(c, d, a, b, x[i + 2], 15, 718787259);
		b = md5ii(b, c, d, a, x[i + 9], 21, -343485551);

		a = safeAdd(a, olda);
		b = safeAdd(b, oldb);
		c = safeAdd(c, oldc);
		d = safeAdd(d, oldd);
	}
	return Array(a, b, c, d);
}

/*
* These functions implement the four basic operations the algorithm uses.
*/
function md5cmn(q, a, b, x, s, t) {
	return safeAdd(bitRol(safeAdd(safeAdd(a, q), safeAdd(x, t)), s), b);
}
function md5ff(a, b, c, d, x, s, t) {
	return md5cmn((b & c) | ((~b) & d), a, b, x, s, t);
}
function md5gg(a, b, c, d, x, s, t) {
	return md5cmn((b & d) | (c & (~d)), a, b, x, s, t);
}
function md5hh(a, b, c, d, x, s, t) {
	return md5cmn(b ^ c ^ d, a, b, x, s, t);
}
function md5ii(a, b, c, d, x, s, t) {
	return md5cmn(c ^ (b | (~d)), a, b, x, s, t);
}

/*
* Calculate the HMAC-MD5, of a key and some data
*/
function coreHmacMd5(key, data) {
	var bkey = str2binl(key);
	if (bkey.length > 16) {
		bkey = coreMd5(bkey, key.length * chrsz);
	}

	var ipad = Array(16);
	var opad = Array(16);
	for (var i = 0; i < 16; i++) {
		ipad[i] = bkey[i] ^ 0x36363636;
		opad[i] = bkey[i] ^ 0x5C5C5C5C;
	}

	var hash = coreMd5(ipad.concat(str2binl(data)), 512 + data.length * chrsz);
	return coreMd5(opad.concat(hash), 512 + 128);
}

/*
* Add integers, wrapping at 2^32. This uses 16-bit operations internally
* to work around bugs in some JS interpreters.
*/
function safeAdd(x, y) {
	var lsw = (x & 0xFFFF) + (y & 0xFFFF);
	var msw = (x >> 16) + (y >> 16) + (lsw >> 16);
	return (msw << 16) | (lsw & 0xFFFF);
}

/*
* Bitwise rotate a 32-bit number to the left.
*/
function bitRol(num, cnt) {
	return (num << cnt) | (num >>> (32 - cnt));
}

/*
* Convert a string to an array of little-endian words
* If chrsz is ASCII, characters >255 have their hi-byte silently ignored.
*/
function str2binl(str) {
	var bin = Array();
	var mask = (1 << chrsz) - 1;
	for (var i = 0; i < str.length * chrsz; i += chrsz) {
		bin[i >> 5] |= (str.charCodeAt(i / chrsz) & mask) << (i % 32);
	}
	return bin;
}

/*
* Convert an array of little-endian words to a string
*/
function binl2str(bin) {
	var str = '';
	var mask = (1 << chrsz) - 1;
	for (var i = 0; i < bin.length * 32; i += chrsz) {
		str += String.fromCharCode((bin[i >> 5] >>> (i % 32)) & mask);
	}
	return str;
}

/*
* Convert an array of little-endian words to a hex string.
*/
function binl2hex(binarray) {
	var hexTab = hexcase ? '0123456789ABCDEF' : '0123456789abcdef';
	var str = '';
	for (var i = 0; i < binarray.length * 4; i++) {
		str	+=	hexTab.charAt((binarray[i >> 2] >> ((i % 4) * 8 + 4)) & 0xF) +
				hexTab.charAt((binarray[i >> 2] >> ((i % 4) * 8)) & 0xF);
	}
	return str;
}

/*
* Convert an array of little-endian words to a base-64 string
*/
function binl2b64(binarray) {
	var tab = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
	var str = '';
	for (var i = 0; i < binarray.length * 4; i += 3) {
		var triplet =	(((binarray[i >> 2] >> 8 * (i % 4)) & 0xFF) << 16) |
						(((binarray[i + 1 >> 2] >> 8 * ((i + 1) % 4)) & 0xFF) << 8) |
						((binarray[i + 2 >> 2] >> 8 * ((i + 2) % 4)) & 0xFF);
		for (var j = 0; j < 4; j++) {
			if (i * 8 + j * 6 > binarray.length * 32) {
				str += b64pad;
			} else {
				str += tab.charAt((triplet >> 6 * (3 - j)) & 0x3F);
			}
		}
	}
	return str;
}

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

/** item_methods.js **/
// © Copyright by Aras Corporation, 2004-2011.

/*
*   The item methods extension for the Aras Object.
*   most of methods in this file use itemID and itemTypeName as parameters
*/

/*-- newFileItem
*
*   Method to create a new item of ItemType File
*   fileNameOrObject = the name of the file or FileObject
*
*/
Aras.prototype.newFileItem = function Aras_newFileItem(fileNameOrObject) {
	var brief_fileName = "";
	if (typeof fileNameOrObject === "string") {
		var parts = fileNameOrObject.split(/[\\\/]/);
		brief_fileName = parts[parts.length - 1];
	} else {
		brief_fileName = fileNameOrObject.name;
	}

	with (this) {
		var item = createXmlElement('Item');
		item.setAttribute('type', 'File');

		item.setAttribute('id', generateNewGUID());
		item.setAttribute('action', 'add');
		item.setAttribute('loaded', '1');
		item.setAttribute('levels', '1');
		item.setAttribute('isTemp', '1');

		setItemProperty(item, 'filename', brief_fileName);
		if (typeof fileNameOrObject === "string") {
			setItemProperty(item, 'checkedout_path', fileNameOrObject.substring(0, fileNameOrObject.length - brief_fileName.length - 1));
		} else {
			setItemProperty(item, 'checkedout_path', '');
			aras.vault.addFileToList(item.getAttribute('id'), fileNameOrObject);
		}
		var fileSize = aras.vault.getFileSize(fileNameOrObject);
		setItemProperty(item, 'file_size', fileSize);

		var locatedItemId = getRelationshipTypeId('Located');
		if (!locatedItemId) {
			AlertError(getResource('', 'item_methods.located_item_type_not_exist'));
			return null;
		}

		var locatedItem = newRelationship(locatedItemId, item, false, null, null);
		var vaultServerID = getVaultServerID();
		if (vaultServerID == '') {
			AlertError(getResource('', 'item_methods.no_defualt_vault_sever'), window);
			return null;
		}
		setItemProperty(locatedItem, 'related_id', vaultServerID);
		return item;
	}
};

/*-- newItem
*
*   Method to create a new item
*   itemTypeName = the name of the ItemType
*
*/
Aras.prototype.newItem = function Aras_newItem(itemTypeName, itemTypeNdOrSpecialArg) {
	var self = this;
	function newItem_internal(arasObj, filePath) {
		var item = null;
		var typeId = itemType.getAttribute('id');
		if (itemTypeName == 'Workflow Map') {
			item = arasObj.newWorkflowMap();
			item.setAttribute('typeId', typeId);
			return item;
		}

		if (itemTypeName === 'File') {
			var fileName = null;
			var isFileNameSpecified = itemTypeNdOrSpecialArg;

			if (isFileNameSpecified) {
				fileName = itemTypeNdOrSpecialArg;
			} else {
				var vault = arasObj.vault;
				fileName = vault.selectFile();
			}

			if (fileName) {
				item = arasObj.newFileItem(fileName);
				item.setAttribute('typeId', typeId);
			}
			return item;
		}

		item = self.createXmlElement('Item');
		item.setAttribute('type', itemTypeName);

		item.setAttribute('id', arasObj.GUIDManager.GetGUID());
		item.setAttribute('action', 'add');
		item.setAttribute('loaded', '1');
		item.setAttribute('levels', '1');
		item.setAttribute('isTemp', '1');
		item.setAttribute('typeId', typeId);

		var properties = itemType.selectNodes('Relationships/Item[@type="Property" and default_value and not(default_value[@is_null="1"])]');

		for (var i = 0; i < properties.length; i++) {
			var property = properties[i];
			var propertyName = arasObj.getItemProperty(property, 'name');
			var dataType = arasObj.getItemProperty(property, 'data_type');
			var defaultValue = arasObj.getItemProperty(property, 'default_value');
			if (dataType == 'item') {
				var dataSource = property.selectSingleNode('data_source');
				if (dataSource) {
					dataSource = dataSource.getAttribute('name');
				}
				if (dataSource) {
					defaultValue = arasObj.getItemById(dataSource, defaultValue, 0);
				}
			}
			arasObj.setItemProperty(item, propertyName, defaultValue, undefined, itemType);
		}

		if (itemTypeName == 'Life Cycle Map') {
			var stateTypeID = arasObj.getRelationshipTypeId('Life Cycle State');
			var newState = arasObj.newRelationship(stateTypeID, item);
			arasObj.setItemProperty(newState, 'name', 'Start');
			arasObj.setItemProperty(newState, 'image', '../images/LifeCycleState.svg');
			arasObj.setItemProperty(item, 'start_state', newState.getAttribute('id'));

		} else if (itemTypeName == 'Form') {
			arasObj.setItemProperty(item, 'stylesheet', '../styles/default.css');
			var relTypeID = arasObj.getRelationshipTypeId('Body');
			var bodyRel = arasObj.newRelationship(relTypeID, item);
		}

		return item;
	}

	var isItemTypeSpecified = itemTypeNdOrSpecialArg && itemTypeNdOrSpecialArg.xml;
	var itemType = isItemTypeSpecified ? itemTypeNdOrSpecialArg : this.getItemTypeForClient(itemTypeName).node;
	if (!itemType) {
		this.AlertError(this.getResource('', 'ui_methods_ex.item_type_not_found', itemTypeName));
		return false;
	}

	function handleNewItemType(newTypeName) {
		if (newTypeName) {
			var new_itemNd = self.newItem(newTypeName);
			self.itemsCache.addItem(new_itemNd);
			return new_itemNd;
		} else {
			return null;
		}
	}

	if (this.isPolymorphic(itemType)) {
		var itemTypesList = this.getMorphaeList(itemType);
		if(itemTypesList.length!=1){
			var selectionDialog = this.uiItemTypeSelectionDialog(itemTypesList, arguments[3]);

			// console.log(selectionDialog);
			if (selectionDialog && selectionDialog.then) {
				// console.log("1");			
				return selectionDialog.then(handleNewItemType);
			} else {
				// console.log("2")
				return handleNewItemType(selectionDialog)
			}
	
		}
		else{
			return ;
		}
		

	}

	var onBeforeNewEv = itemType.selectNodes('//Item[client_event="OnBeforeNew"]/related_id/Item');
	var onAfterNewEv = itemType.selectNodes('//Item[client_event="OnAfterNew"]/related_id/Item');
	var onNewEv = itemType.selectSingleNode('//Item[client_event="OnNew"]/related_id/Item');

	var res;
	var xml = '<Item type=\'' + itemTypeName + '\'/>';

	if (onBeforeNewEv.length) {
		for (var i = 0; i < onBeforeNewEv.length; i++) {
			try {
				res = this.evalMethod(this.getItemProperty(onBeforeNewEv[i], 'name'), xml);
			} catch (exp) {
				this.AlertError(this.getResource('', 'item_methods.event_handler_failed'), this.getResource('', 'item_methods.event_handler_failed_with_message', exp.description), this.getResource('', 'common.client_side_err'));
				return null;
			}
			if (res === false) {
				return null;
			}
		}
	}
	if (onNewEv) {
		res = this.evalMethod(this.getItemProperty(onNewEv, 'name'), xml);
		if (res) {
			res = res.node;
		}
		if (!res) {
			return null;
		}
	} else {
		res = newItem_internal(this);
	}

	if (onAfterNewEv.length && res) {
		for (var i = 0; i < onAfterNewEv.length; i++) {
			try {
				res = this.evalMethod(this.getItemProperty(onAfterNewEv[i], 'name'), res.xml);
			} catch (exp) {
				this.AlertError(this.getResource('', 'item_methods.event_handler_failed'), this.getResource('', 'item_methods.event_handler_failed_with_message', exp.description), this.getResource('', 'common.client_side_err'));
				return null;
			}

			if (res) {
				res = res.node;
			}
			if (!res) {
				return null;
			}
		}
	}

	if (onNewEv) {
		for (var name in this.windowsByName) {
			try {
				var win = this.windowsByName[name];
				if (win && win.onRefresh) {
					win.onRefresh();
				}
			} catch (excep) {}
		}
		res = null;
	}

	return res;
};

/*
* this function add item to packageDefinition
*/
Aras.prototype.addItemToPackageDef = function(strArrOfId, itemTypeName) {
	//check if items selected in grid
	if (strArrOfId.length < 1) {
		return;
	}
	var ArasObj = this;
	var arrayOfPacakge = [];
	var packArray = null;
	var countOfPacks = 0;
	var itemTypeLabel = '';
	var itemTypeId = this.getItemTypeId(itemTypeName);


	// We need to replace id with config_id.
	var copyOfIds = new Array();
	for (var i = 0; i < strArrOfId.length; i++) {
		copyOfIds.push('\'' + strArrOfId[i] + '\'');
	}

	var aml = '<Item type=\'' + itemTypeName + '\' action=\'get\' select=\'config_id\'><id condition=\'in\'>' + copyOfIds.join(',') + '</id></Item>';
	var res = this.soapSend('ApplyItem', aml);
	if (res.getFaultCode() != 0) {
		this.AlertError(res);
		return;
	}
	res = res.getResultsBody();
	var result = this.createXMLDocument();
	result.loadXML(res);

	if (result.selectNodes('./Result').length === 1) {
		result = result.selectSingleNode('./Result');
	}
	for (var i = 0; i < result.selectNodes('./Item').length; i++) {
		strArrOfId[i] = result.selectSingleNode('./Item[id=\'' + strArrOfId[i] + '\']/config_id').text;
	}

	//check if PackageDefinition exist
	var packageDefId = this.getItemTypeId('PackageDefinition');
	if (!packageDefId) {
		ArasObj.AlertError(this.getResource('', 'item_methods.unable_get_package_definition_item_type'));
		return;
	}

	//getting the label of ItemType
	var itemType = this.getItemTypeForClient(itemTypeName);
	if (itemType) {
		//IR-014145 'Problem report with 'Add To Package Definition'' fix: we need only "en" label.
		var qyItemWithEnLbl = new this.getMostTopWindowWithAras(window).Item();
		qyItemWithEnLbl.setAction('get');
		qyItemWithEnLbl.setType('ItemType');
		qyItemWithEnLbl.setProperty('name', itemTypeName);
		qyItemWithEnLbl.setAttribute('select', '*');
		qyItemWithEnLbl.setAttribute('language', 'en');
		resItemWithEnLbl = qyItemWithEnLbl.apply();
		itemTypeLabel = resItemWithEnLbl.getProperty('label', undefined, 'en');

		if (itemTypeLabel === undefined) {
			itemTypeLabel = itemTypeName;
		}
	} else {
		ArasObj.AlertError(this.getResource('', 'item_methods.unable_get_item_type', itemTypeName), ArasObj.getFaultString(qry.dom), ArasObj.getFaultActor(qry.dom));
		return;
	}

	//query all packages existing in DBO
	getAllpackages();

	function ApplyItemInternal(action, type, attr, props) {
		var query = new ArasObj.getMostTopWindowWithAras(window).Item();
		query.setAction(action);
		query.setType(type);
		query.setAttribute('doGetItem', 0);

		f(attr, true);
		f(props);

		function f(arr, isAttr) {
			if (arr && arr.length != 0) {
				for (var i = 0; i < arr.length; i++) {
					var tmp = arr[i].split('|');
					if (isAttr) {
						query.setAttribute(tmp[0], tmp[1]);
					} else {
						query.setProperty(tmp[0], tmp[1]);
					}
				}
			}
		}
		return query.apply();
	}

	/*
	* this function request all packages
	*/
	function getAllpackages() {
		packArray = ApplyItemInternal('get', 'PackageDefinition', new Array('select|name, id'), new Array('is_current|1'));
		countOfPacks = packArray.getItemCount();
	}

	/***
	 * Add selected itemtype to package
	 * @param strSelectedPack name of package
	 */
	function addItemsToPackage(strSelectedPack) {
		// Get id of PackageDefinition
		var strIdOfPackNode = packArray.dom.selectSingleNode('.//Result/Item[name=\'' + strSelectedPack + '\']/id');

		// If user didn't checked any package
		if (!strIdOfPackNode) {
			return;
		}

		var strIdOfPack = strIdOfPackNode.text;

		// Get id of PackageGroup
		var qry = ApplyItemInternal('get', 'PackageGroup', new Array('select|id'), new Array('source_id|' + strIdOfPack, 'name|' + itemTypeLabel));
		// In case group not exist create new one
		if (qry.isError()) {
			qry = ApplyItemInternal('add', 'PackageGroup', null, new Array('source_id|' + strIdOfPack, 'name|' + itemTypeLabel));
			if (qry.isError()) {
				ArasObj.AlertError(ArasObj.getResource('', 'item_methods.unable_add_group', itemTypeLabel), ArasObj.getFaultString(qry.dom), ArasObj.getFaultActor(qry.dom));
				return;
			}
		}
		var strIdOfGroup = qry.getAttribute('id');
		var bWasError = false;

		for (var i = 0; i < strArrOfId.length; i++) {
			var strKeyedName = ArasObj.getKeyedName(strArrOfId[i], itemTypeName);
			qry = ApplyItemInternal('get', 'PackageElement', new Array('select|id'), new Array('source_id|' + strIdOfGroup, 'element_id|' + strArrOfId[i]));
			if (qry.isError()) {
				qry = ApplyItemInternal('add', 'PackageElement', null, new Array('source_id|' + strIdOfGroup, 'element_id|' + strArrOfId[i], 'name|' + strKeyedName, 'element_type|' + itemTypeName));
				if (qry.isError()) {
					bWasError = true;
					ArasObj.AlertError(ArasObj.getResource('', 'item_methods.unable_add_item', strKeyedName), ArasObj.getFaultString(qry.dom), ArasObj.getFaultActor(qry.dom));
				}
			} else {
				bWasError = true;
				ArasObj.AlertError(ArasObj.getResource('', 'item_methods.item_already_exsist_in_package', strKeyedName, strSelectedPack));
			}
		}

		if (!bWasError) {
			if (strArrOfId.length > 1) {
				ArasObj.AlertSuccess(ArasObj.getResource('', 'item_methods.items_added_successfully'));
			} else {
				ArasObj.AlertSuccess(ArasObj.getResource('', 'item_methods.item_added_successfully'));
			}
		}
	}

	/*
	*param strNameOfPack   - name of new package to be created
	*param strArrdependOns - array of package names to be depended by new package
	*/
	function createPackage(strNameOfPack, strArrdependOns) {
		qry = ArasObj.getItemFromServerByName('PackageDefinition', strNameOfPack, 'id');
		if (qry && !qry.isError()) {
			ArasObj.AlertError(ArasObj.getResource('', 'item_methods.package_with_such_name_already_exist'));
			return false;
		} else {
			qry = ApplyItemInternal('add', 'PackageDefinition', null, new Array('name|' + strNameOfPack));
			if (qry.isError()) {
				ArasObj.AlertError(ArasObj.getResource('', 'item_methods.unable_add_package_with_name', strNameOfPack), ArasObj.getFaultString(qry.dom), ArasObj.getFaultActor(qry.dom));
				return false;
			}

			var strIdOfpack = qry.node.getAttribute('id');
			for (var i = 0; i < strArrdependOns.length; i++) {
				qry = ApplyItemInternal('add', 'PackageDependsOn', null, new Array('name|' + strArrdependOns[i], 'source_id|' + strIdOfpack));
				if (qry.isError()) {
					ArasObj.AlertError(ArasObj.getResource('', 'item_methods.Unable to add dependency', strArrdependOns[i]), ArasObj.getFaultString(qry.dom), ArasObj.getFaultActor(qry.dom));
					return false;
				}
			}
		}
		return true;
	}

	for(var i = 0; i < packArray.getItemCount(); i++) {
		var packItem = packArray.getItemByIndex(i);
		var propName = packItem.getProperty('name');
		arrayOfPacakge.push(propName);
	}
	var topWindow = this.getMostTopWindowWithAras(window);
	topWindow.ArasCore.Dialogs.selectPackageDefinition(arrayOfPacakge).then(function(packageName) {
		if (!packageName) {
			return;
		}
		if (packageName === 'create new') {
			return topWindow.ArasCore.Dialogs.createNewPackage(arrayOfPacakge).then(
				function(objectNewPack) {
					if (objectNewPack && objectNewPack.packageName) {
						var bResult = createPackage(objectNewPack.packageName, objectNewPack.dependency);
						if (bResult) {
							getAllpackages();
							addItemsToPackage(objectNewPack.packageName);
						}
					}
				}
			);
		}
		addItemsToPackage(packageName);
	});
};

/*-- newRelationship
*
*   Method to create a new Relationship for an item
*   relTypeId = the RelatinshpType id
*   srcItem   = the source item in the relationship (may be null:i.e. when created with mainMenu)
*   searchDialog = true or false : if search dialog to be displayed
*   wnd =  the window from which the dialog is opened
*
*/
Aras.prototype.newRelationship = function(relTypeId, srcItem, searchDialog, wnd, relatedItem, relatedTypeName, bTestRelatedItemArg, bIsDoGetItemArg, descByTypeName) {
	with (this) {
		var processAddingRelationship = function(relatedItem) {
			if (descByTypeName == undefined) {
				descByTypeName = this.getItemTypeName(descByTypeId);
			}

			var descByItem = this.newItem(descByTypeName);
			this.itemsCache.addItem(descByItem);
			if (!descByItem) {
				return null;
			}

			if (relatedId != '' && !descByItem.selectSingleNode('related_id')) {
				this.createXmlElement('related_id', descByItem);
			}
			if (relatedItem) {
				if (srcItem) {
					if (relatedItem == srcItem) {
						relatedItem = srcItem.cloneNode(true);
						var relationshipsNd = relatedItem.selectSingleNode('Relationships');
						if (relationshipsNd) {
							relatedItem.removeChild(relationshipsNd);
						}
						relationshipsNd = null;
						relatedItem.setAttribute('action', 'skip');
					}
				}

				if (this.isTempID(relatedId)) {
					descByItem.selectSingleNode('related_id').appendChild(relatedItem);
				} else {
					descByItem.selectSingleNode('related_id').appendChild(relatedItem.cloneNode(true));
				}
			}

			if (relTypeName == 'RelationshipType') {
				if (srcItem) {
					this.setItemProperty(descByItem, 'source_id', srcItem.getAttribute('id'));
				}
			}

			if (srcItem) {
				if (!srcItem.selectSingleNode('Relationships')) {
					srcItem.appendChild(srcItem.ownerDocument.createElement('Relationships'));
				}

				var relationship;
				try {
					relationship = srcItem.selectSingleNode('Relationships').appendChild(descByItem);
					//        relationship = srcItem.selectSingleNode('Relationships').appendChild(descByItem.cloneNode(true));
				} catch (excep) {
					if (excep.number == -2147467259) {
						this.AlertError(this.getResource('', 'item_methods.recursion_not_allowed_here'), wnd);
						return null;
					} else {
						throw excep;
					}
				}

				relationship.setAttribute('typeId', descByTypeId);
				relationship.setAttribute('action', 'add');
				relationship.setAttribute('loaded', '1');
				relationship.setAttribute('levels', '0');

				if (bIsDoGetItem) {
					relationship.setAttribute('doGetItem', '0');
				}

				this.setItemProperty(relationship, 'source_id', srcItem.getAttribute('id'));

				//      descByItem.parentNode.removeChild(descByItem);

				return relationship;
			} else {
				return descByItem;
			}
		}

		var bTestRelatedItem;
		if (bTestRelatedItemArg == undefined) {
			bTestRelatedItem = false;
		} else {
			bTestRelatedItem = bTestRelatedItemArg;
		}

		var bIsDoGetItem;
		if (bIsDoGetItemArg == undefined) {
			bIsDoGetItem = false;
		} else {
			bIsDoGetItem = bIsDoGetItemArg;
		}

		var srcItemID;
		if (srcItem) {
			srcItemID = srcItem.getAttribute('id');
			if (!wnd) {
				wnd = uiFindWindowEx(srcItemID);
				if (!wnd) {
					wnd = window;
				}
			}
		} else if (!wnd) {
			wnd = window;
		}

		relType = getRelationshipType(relTypeId).node;
		var relTypeName = getItemProperty(relType, 'name');
		var relatedTypeId = getItemProperty(relType, 'related_id');
		var descByTypeId = getItemProperty(relType, 'relationship_id');
		var relatedId = '';

		if (relatedItem) {
			relatedId = relatedItem.getAttribute('id');
		}

		var self = this;
		if (relatedTypeId) {
			if (relatedTypeName == undefined) {
				relatedTypeName = getItemTypeName(relatedTypeId);
			}

			if (searchDialog) {
				var params = {
					aras: this.getMostTopWindowWithAras(wnd).aras,
					itemtypeName: relatedTypeName,
					sourceItemTypeName: ((srcItem && srcItem.xml) ? srcItem.getAttribute('type') : ''),
					sourcePropertyName: 'related_id',
					type: 'SearchDialog'
				};
				wnd.ArasModules.MaximazableDialog.show('iframe', params);

				if (relatedId == undefined) {
					return null;
				}

				relatedId = relatedId.itemID;
				if (!relatedId) {
					return null;
				}

				// TODO: should be done in memory no need to call the server
				relatedItem = getItemFromServer(relatedTypeName, relatedId, 'id').node;
			} else {
				if ((relatedItem === undefined) || (bTestRelatedItem == true)) {
					relatedItem = newItem(relatedTypeName, null, wnd);
					if (relatedItem && relatedItem.then) {
						return relatedItem.then(function(relatedItem) {
							this.itemsCache.addItem(relatedItem);
							if (!relatedItem) {
								return null;
							}
							relatedId = relatedItem.getAttribute('id');
							return processAddingRelationship.call(this, relatedItem);
						}.bind(this));
					} else {
						this.itemsCache.addItem(relatedItem);
						if (!relatedItem) {
							return null;
						}
						relatedId = relatedItem.getAttribute('id');
						return processAddingRelationship.call(this, relatedItem);
					}
				}
			}
		}





		return processAddingRelationship.call(this, relatedItem);
	}
};

/*-- copyItem
*
*   Method to copy an item
*   item = item to be cloned
*
*/
Aras.prototype.copyItem = function(itemTypeName, itemID) {
	if (itemID == undefined) {
		return null;
	}

	var itemNd = this.getItemById('', itemID, 0);
	if (itemNd) {
		return this.copyItemEx(itemNd);
	} else {
		if (itemTypeName == undefined) {
			return null;
		}

		var bodyStr = '<Item type="' + itemTypeName + '" id="' + itemID + '" ';
		if (itemTypeName.search(/^ItemType$|^RelationshipType$|^User$/) == 0) {
			bodyStr += ' action="copy" />';
		} else {
			bodyStr += ' action="copyAsNew" />';
		}

		var res = null;

		with (this) {
			var statusId = showStatusMessage('status', this.getResource('', 'common.copying_item'), system_progressbar1_gif);
			res = soapSend('ApplyItem', bodyStr);
			clearStatusMessage(statusId);
		}

		if (res.getFaultCode() != 0) {
			var win = this.uiFindWindowEx(itemID);
			if (!win) {
				win = window;
			}
			this.AlertError(res, win);
			return null;
		}

		var itemCopy = res.results.selectSingleNode('//Item');
		return itemCopy;
	}
};

/*-- saveItem
*
*   Method to save an item
*   itemID = the id for the item to be saved
*   confirmSuccess
*/
Aras.prototype.saveItem = function(itemID, confirmSuccess) {
	if (!itemID) {
		return null;
	}
	var itemNd = this.getFromCache(itemID);
	if (!itemNd) {
		return null;
	} else {
		return this.saveItemEx(itemNd, confirmSuccess);
	}
};

/*-- addItem
*
*   Method to add an item
*   itemID = the id for the item
*
*/
Aras.prototype.addItem = function(itemID) {
	if (!itemID) {
		return false;
	}
	var itemNd = this.getItemById('', itemID, 0);
	if (!itemNd) {
		return false;
	} else {
		return this.saveItemEx(itemNd);
	}
};

/*-- updateItem
*
*   Method to update an item
*   itemID = the id for the item
*
*/
Aras.prototype.updateItem = function(itemID) {
	if (!itemID) {
		return false;
	}
	var itemNd = this.getItemById('', itemID, 0);
	if (!itemNd) {
		return false;
	} else {
		return this.saveItemEx(itemNd);
	}
};

/*-- versionItem
*
*   Method to version the item
*   id = the id for the item
*
*/
Aras.prototype.versionItem = function(itemTypeName, itemID) {
	if (!itemID) {
		return false;
	}
	var win = this.uiFindWindowEx(itemID);
	if (win) {
		win.close(null, true);
		if (this.uiFindWindowEx(itemID)) {
			this.AlertError(this.getResource('', 'item_methods.cannot_close_item_window'));
			return false;
		}
	}
	var itemNd = this.getItemById('', itemID, 0);
	if (!itemNd) {
		return false;
	} else {
		var res = this.saveItemEx(itemNd, true, true);
		if (res && win) {
			this.uiShowItemEx(res);
		}
		return res;
	}
};

Aras.prototype.getAffectedItems = function(itemTypeName, itemId) {
	var res;
	with (this) {
		var statusId = showStatusMessage('status', getResource('', 'item_methods.getting_affected_items'), system_progressbar1_gif);
		res = soapSend('ApplyItem', '<Item type=\'' + itemTypeName + '\' id=\'' + itemId + '\' action=\'getAffectedItems\'/>');
		clearStatusMessage(statusId);
	}

	if (res.getFaultCode() != 0) {
		this.AlertError(res);
		return null;
	}

	return res.results.selectNodes('//Item');
}; //function getAffectedItems

Aras.prototype.purgeItem = function Aras_purgeItem(itemTypeName, itemID, silentMode) {
	/*-- purgeItem
	*
	*   Method to delete the latest version of the item (or the item if it's not versionable)
	*   itemTypeName -
	*   itemID = the id for the item
	*   silentMode - flag to know if user confirmation is NOT needed
	*
	*/

	return this.PurgeAndDeleteItem_CommonPart(itemTypeName, itemID, silentMode, 'purge');
};

Aras.prototype.deleteItem = function Aras_deleteItem(itemTypeName, itemID, silentMode) {
	/*-- deleteItem
	*
	*   Method to delete all versions of the item
	*   itemTypeName -
	*   itemID = the id for the item
	*   silentMode - flag to know if user confirmation is NOT needed
	*
	*/
	var itemType = this.getItemTypeForClient(itemTypeName).node;

	if (aras.isPolymorphic(itemType)) {
		var itemTypesList = this.getMorphaeList(itemType);
		if(itemTypesList.length==1){
			itemTypeName=itemTypesList[0].name;
		}
	}
	

	return this.PurgeAndDeleteItem_CommonPart(itemTypeName, itemID, silentMode, 'delete');
};

Aras.prototype.GetOperationName_PurgeAndDeleteItem = function Aras_GetOperationName_PurgeAndDeleteItem(purgeORdelete) {
	return purgeORdelete == 'delete' ? 'Deleting' : 'Purge';
};

Aras.prototype.Confirm_PurgeAndDeleteItem = function Aras_Confirm_PurgeAndDeleteItem(itemId, keyedName, purgeORdelete) {
	var dialogMessageResourceKey = 'item_methods.' + (purgeORdelete === 'delete' ? 'delete_confirmation' : 'purge_confirmation');
	var win = this.uiFindWindowEx(itemId);
	var options = {dialogWidth: 300, dialogHeight: 180, center: true},
		params = {
			aras: this,
			message: this.getResource('', dialogMessageResourceKey, keyedName),
			buttons: {
				btnYes: this.getResource('', 'common.ok'),
				btnCancel: this.getResource('', 'common.cancel')
			},
			defaultButton: 'btnCancel'
		},
		returnedValue;

	if (!win) {
		win = window;
	}
	win.focus();

	if (this.Browser.isCh()) {
		returnedValue = 'btnCancel';
		if (window.confirm(params.message)) {
			returnedValue = 'btnYes';
		}
	} else {
		returnedValue = this.modalDialogHelper.show('DefaultModal', window, params, options, 'groupChgsDialog.html');
	}

	if(returnedValue === 'btnYes'){
		return true;
	} else {
		return false;
	}
};

Aras.prototype.SendSoap_PurgeAndDeleteItem = function Aras_SendSoap_PurgeAndDeleteItem(ItemTypeName, ItemId, purgeORdelete) {
	/*-- SendSoap_PurgeAndDeleteItem
	*
	*   This method is for ***internal purposes only***.
	*
	*/

	var Operation = this.GetOperationName_PurgeAndDeleteItem(purgeORdelete);
	var StatusId = this.showStatusMessage('status', this.getResource('', 'item_methods.operation_item', Operation), system_progressbar1_gif);
	var res = this.soapSend('ApplyItem', '<Item type=\'' + ItemTypeName + '\' id=\'' + ItemId + '\' action=\'' + purgeORdelete + '\' />', null, false);
	this.clearStatusMessage(StatusId);

	if (res.getFaultCode() != 0) {
		var win = this.uiFindWindowEx(ItemId);
		if (!win) {
			win = window;
		}

		this.AlertError(res, win);
		return false;
	}

	return true;
};

Aras.prototype.RemoveGarbage_PurgeAndDeleteItem = function Aras_RemoveGarbage_PurgeAndDeleteItem(ItemTypeName, ItemId, DeletedItemTypeName, relationship_id) {
	/*-- RemoveGarbage_PurgeAndDeleteItem
	*
	*   This method is for ***internal purposes only***.
	*
	*/
	if (ItemTypeName == 'ItemType' || ItemTypeName == 'RelationshipType') {
		if (DeletedItemTypeName) {
			//remove instances of the deleted ItemType
			this.itemsCache.deleteItems('/Innovator/Items/Item[@type=\'' + DeletedItemTypeName + '\']');
			// TODO: remove mainWnd.Cache also.
		}
		if (relationship_id) {
			//remove corresponding ItemType or RelationshipType
			this.itemsCache.deleteItems('/Innovator/Items/Item[@id=\'' + relationship_id + '\']');
			this.itemsCache.deleteItems('/Innovator/Items/Item[@type=\'RelationshipType\'][relationship_id=\'' + relationship_id + '\']');
		}
	}

	//find and remove all duplicates in dom
	//this helps to fix IR-006266 for example
	this.itemsCache.deleteItems('/Innovator/Items//Item[@id=\'' + ItemId + '\']');
};

Aras.prototype.PurgeAndDeleteItem_CommonPart = function Aras_PurgeAndDeleteItem_CommonPart(ItemTypeName, ItemId, silentMode, purgeORdelete) {
	/*-- PurgeAndDeleteItem_CommonPart
	*
	*   This method is for ***internal purposes only***.
	*   Is allowed to be called only from inside aras.deleteItem and aras.purgeItem methods.
	*
	*/
	if (silentMode === undefined) {
		silentMode = false;
	}
	var itemNd = this.itemsCache.getItem(ItemId);

	if (itemNd) {
		return this.PurgeAndDeleteItem_CommonPartEx(itemNd, silentMode, purgeORdelete);
	} else {
		//prepare
		if (!silentMode) {
			if (!this.Confirm_PurgeAndDeleteItem(ItemId, this.getKeyedName(ItemId), purgeORdelete)) {
				return false;
			}
		}

		var DeletedItemTypeName;
		var relationship_id;
		if (!this.isTempID(ItemId)) {
			//save some information
			if (ItemTypeName == 'ItemType') {
				var tmpItemTypeNd = this.getItemFromServer('ItemType', ItemId, 'name,is_relationship');
				if (tmpItemTypeNd) {
					tmpItemTypeNd = tmpItemTypeNd.node; //because getItemFromServer returns IOM Item...
				}
				if (tmpItemTypeNd) {
					if (this.getItemProperty(tmpItemTypeNd, 'is_relationship') == '1') {
						relationship_id = ItemId;
					}
					DeletedItemTypeName = this.getItemProperty(tmpItemTypeNd, 'name');
				}
				tmpItemTypeNd = null;
			} else if (ItemTypeName == 'RelationshipType') {
				var tmpRelationshipTypeNd = this.getItemFromServer('RelationshipType', ItemId, 'relationship_id,name');
				if (tmpRelationshipTypeNd) {
					tmpRelationshipTypeNd = tmpRelationshipTypeNd.node; //because getItemFromServer returns IOM Item...
				}
				if (tmpRelationshipTypeNd) {
					relationship_id = this.getItemProperty(tmpRelationshipTypeNd, 'relationship_id');
					DeletedItemTypeName = this.getItemProperty(tmpRelationshipTypeNd, 'name');
				}
				tmpRelationshipTypeNd = null;
			} else if (ItemTypeName == 'Preference') {
				this.deleteSavedSearchesByPreferenceIDs([ItemId]);
			}
			//delete
			if (!this.SendSoap_PurgeAndDeleteItem(ItemTypeName, ItemId, purgeORdelete)) {
				return false;
			}
		}

		//delete all dependent stuff
		if (ItemTypeName == 'ItemType' || ItemTypeName == 'RelationshipType') {
			this.RemoveGarbage_PurgeAndDeleteItem(ItemTypeName, ItemId, DeletedItemTypeName, relationship_id);
		}

		this.MetadataCache.RemoveItemById(ItemId);
	}

	return true;
};

Aras.prototype.deleteSavedSearchesByPreferenceIDs = function Aras_deleteSavedSearchesByPreferenceIDs(preferenceIDs) {
	var idsString = '\'' + preferenceIDs.join('\',\'') + '\'';

	var qry = this.newIOMItem('SavedSearch', 'get');
	qry.SetAttribute('select', 'id');
	qry.SetAttribute('where', '[SavedSearch].owned_by_id in (SELECT identity_id FROM [Preference] WHERE id in (' + idsString + ')) AND [SavedSearch].auto_saved=\'1\'');
	qry.SetProperty('auto_saved', '1');
	var res = qry.apply();

	if (!res.isEmpty() && !res.isError()) {
		var items = res.getItemsByXPath(this.XPathResult('/Item[@type=\'SavedSearch\']'));
		for (var i = 0; i < items.getItemCount(); i++) {
			this.MetadataCache.RemoveItemById(items.getItemByIndex(i).getID());
		}

		var deleteSavedSearchesAml = '<AML>' +
			'	<Item type=\'SavedSearch\' action=\'delete\' where="[SavedSearch].owned_by_id in (SELECT identity_id FROM [Preference] WHERE id in (' + idsString + ')) AND [SavedSearch].auto_saved=\'1\'">' +
			'	</Item>' +
			'</AML>';

		res = this.applyAML(deleteSavedSearchesAml);
	}
};

Aras.prototype.deletePreferences = function Aras_deletePreferences(preferenceIDs) {
	var StatusId = this.showStatusMessage('status', this.getResource('', 'item_methods.operation_item', 'Deleting'), system_progressbar1_gif);
	try {
		for (var preferenceIndex = 0; preferenceIndex < preferenceIDs.length; preferenceIndex++) {
			var preferenceId = preferenceIDs[preferenceIndex];
			this.MetadataCache.RemoveItemById(preferenceId);
		}

		var idsString = '\'' + preferenceIDs.join('\',\'') + '\'';

		this.deleteSavedSearchesByPreferenceIDs(preferenceIDs);

		var deletePreferencesAml = '<AML>' +
			'	<Item type=\'Preference\' action=\'delete\' where="[Preference].id in (' + idsString + ')"/>' +
			'</AML>';

		res = this.applyAML(deletePreferencesAml);

		allChecked = false;
	} finally {
		this.clearStatusMessage(StatusId);
	}
};

/*-- lockItem
*
*   Method to lock the item
*   id = the id for the item
*
*/
Aras.prototype.lockItem = function Aras_lockItem(itemID, itemTypeName) {
	if (itemID) {
		var itemNode = this.getFromCache(itemID);

		if (itemNode) {
			return this.lockItemEx(itemNode);
		} else {
			if (itemTypeName) {
				var ownerWindow = this.uiFindWindowEx(itemID) || window,
					bodyStr = '<Item type=\'' + itemTypeName + '\' id=\'' + itemID + '\' action=\'lock\' />',
					statusId = this.showStatusMessage('status', this.getResource('', 'common.locking_item_type', itemTypeName), system_progressbar1_gif),
					requestResult = this.soapSend('ApplyItem', bodyStr);

				this.clearStatusMessage(statusId);

				if (requestResult.getFaultCode() != 0) {
					this.AlertError(requestResult, ownerWindow);
					return null;
				}

				itemNode = requestResult.results.selectSingleNode(this.XPathResult('/Item'));
				if (itemNode) {
					this.updateInCache(itemNode);
					itemNode = this.getFromCache(itemID);

					this.fireEvent('ItemLock', {
						itemID: itemNode.getAttribute('id'),
						itemNd: itemNode,
						newLockedValue: this.isLocked(itemNode)
					});
					return itemNode;
				} else {
					this.AlertError(this.getResource('', 'item_methods.failed_get_item_type', itemTypeName), this.getResource('', 'item_methods.xpathresult_of_item_returned_null'), 'common.client_side_err', ownerWindow);
					return null;
				}
			} else {
				return null;
			}
		}
	}

	return false;
};

/*-- unlockItem
*
*   Method to unlock the item
*   id = the id for the item
*
*/
Aras.prototype.unlockItem = function(itemID, itemTypeName) {
	if (!itemID) {
		return null;
	}

	with (this) {
		var itemNd = getFromCache(itemID);
		if (itemNd) {
			return unlockItemEx(itemNd);
		} else {
			if (!itemTypeName) {
				return null;
			} else {
				var win = uiFindWindowEx(itemID);
				if (!win) {
					win = window;
				}

				var bodyStr = '<Item type="' + itemTypeName + '" id="' + itemID + '" action="unlock" />';
				var statusId = showStatusMessage('status', getResource('', 'item_methods.unlocking_item'), system_progressbar1_gif);
				var res = soapSend('ApplyItem', bodyStr);
				clearStatusMessage(statusId);

				if (res.getFaultCode() != 0) {
					this.AlertError(res, win);
					return null;
				}

				itemNd = res.results.selectSingleNode(XPathResult('/Item'));
				if (!itemNd) {
					return null;
				}

				updateInCache(itemNd);
				updateFilesInCache(itemNd);

				var params = this.newObject();
				params.itemID = itemNd.getAttribute('id');
				params.itemNd = itemNd;
				params.newLockedValue = this.isLocked(itemNd);
				this.fireEvent('ItemLock', params);

				return itemNd;
			}
		}
	} //with (this)
};

/*-- loadItems
*
*   Method to load an item or items
*   typeName   = the ItemType name
*   body       = the query message to get the items
*   levels     = the levels deep for the returned item configuration
*   pageSize   = the number of rows to return
*   page       = the page number
*   configPath = the RelationshipType names to include inteh item configuration returned
*   select     = the list of properties to return
*
*/
Aras.prototype.loadItems = function Aras_loadItems(typeName, body, levels, pageSize, page, configPath, select) {
	if (typeName == undefined || typeName == '') {
		return false;
	}
	if (body == undefined) {
		body = '';
	}
	if (levels == undefined) {
		levels = 0;
	}
	if (pageSize == undefined) {
		pageSize = '';
	}
	if (page == undefined) {
		page = '';
	}
	if (configPath == undefined) {
		configPath = '';
	}
	if (select == undefined) {
		select = '';
	}
	levels = parseInt(levels);

	var attrs = '', innerBody = '';
	if (body != '') {
		if (body.charAt(0) != '<') {
			attrs = body;
		} else {
			innerBody = body;
		}
	}

	var soapBody = '<Item type="' + typeName + '" levels="' + levels + '" action="get" ';
	if (pageSize != '') {
		soapBody += 'pagesize="' + pageSize + '" ';
	}
	if (page != '') {
		soapBody += 'page="' + page + '" ';
	}
	if (configPath != '') {
		soapBody += 'config_path="' + configPath + '" ';
	}
	if (select != '') {
		soapBody += 'select="' + select + '" ';
	}
	soapBody += attrs + '>' + innerBody + '</Item>';

	var res;
	with (this) {
		var statusId = showStatusMessage('status', getResource('', 'item_methods.loading', typeName), system_progressbar1_gif);
		res = soapSend('ApplyItem', soapBody);
		clearStatusMessage(statusId);
	}

	if (res.getFaultCode() != 0) {
		if (this.DEBUG) {
			this.AlertError(this.getResource('', 'item_methods.fault_loading'), typeName, res.getFaultCode());
		}
		return null;
	}

	if (configPath) {
		levels--;
	}

	var items = res.results.selectNodes(this.XPathResult('/Item'));
	var itemsRes = new Array();
	for (var i = 0; i < items.length; ++i) {
		var item = items[i];
		var currentId = item.getAttribute('id');
		item.setAttribute('levels', levels);
		this.itemsCache.updateItem(item, true);
		itemsRes.push(this.itemsCache.getItem(currentId));
	}

	return itemsRes;
};

/*-- getItem
*
*   Method to load an item
*   typeName   = the ItemType name
*   xpath      = the XPath to teh item in the dom cache
*   body       = the query message to get the items
*   levels     = the levels deep for the returned item configuration
*   configPath = the RelationshipType names to include inteh item configuration returned
*   select     = the list of properties to return
*
*/
Aras.prototype.getItem = function(itemTypeName, xpath, body, levels, configPath, select) {
	if (levels == undefined) {
		levels = 1;
	}
	if (typeof (itemTypeName) != 'string') {
		itemTypeName = '';
	}

	var typeAttr = '';
	if (xpath.indexOf('@id=') < 0) {
		/* POLYITEM: only argument with @type if xpath does not start with @id= */
		typeAttr = '[@type="' + itemTypeName + '"]';
	}

	xpath = '/Innovator/Items/Item' + typeAttr + '[' + xpath + ']';
	var node = this.itemsCache.getItemByXPath(xpath);

	var loadItemFromServer = false;

	// if node was found in cache
	if (node) {
		// if node is dirty then retreive node from cache after test for completeness
		if (this.isDirtyEx(node) || this.isTempEx(node)) {
			// if requested levels > than node levels attribute then load item from server
			if ((node.getAttribute('levels') - levels) < 0) {
				itemTypeName = node.getAttribute('type');
				loadItemFromServer = true;
			}
		} else {// if node not dirty then drop it from cache and load from server original version
			if (!itemTypeName) {
				itemTypeName = node.getAttribute('type');
			}
			loadItemFromServer = true;
		}
	} else {// if node not exists in cache then load item from server
		if (itemTypeName != '') {
			loadItemFromServer = true;
		}
	}

	if (loadItemFromServer) {
		this.loadItems(itemTypeName, body, levels, '', '', configPath, select);
		node = this.itemsCache.getItemByXPath(xpath);
	}

	return node;
};

/*-- getRelatedItem
*
*   Method to get related item from relationship
*   item        = relationship from which related item will be taken
*
*/
Aras.prototype.getRelatedItem = function(item) {
	try {
		var relatedItem = item.selectSingleNode('related_id/Item');
		return relatedItem;
	} catch (excep) {
		return null;
	}
};

/*-- getItemById
*
*   Method to load an item by id
*   typeName   = the ItemType name
*   id         = the id for the item
*   levels     = the levels deep for the returned item configuration
*   configPath = the RelationshipType names to include inteh item configuration returned
*   select     = the list of properties to return
*
*/
Aras.prototype.getItemById = function(typeName, id, levels, configPath, select) {
	if (id == '') {
		return null;
	}
	if (levels == undefined) {
		levels = 1;
	}
	if (configPath == undefined) {
		configPath = '';
	}
	if (select == undefined) {
		select = '';
	}

	return this.getItem(typeName, '@id="' + id + '"', 'id="' + id + '"', levels, configPath, select);
};

/*-- getItemUsingIdAsParameter
*
*   The same as getItemById. The only difference is that method load an item by id passing id like parameter,
*   not like attribute. Created because if request item using id as attribute, server will return full item.
*   typeName   = the ItemType name
*   id         = the id for the item
*   levels     = the levels deep for the returned item configuration
*   configPath = the RelationshipType names to include inteh item configuration returned
*   select     = the list of properties to return
*
*/
Aras.prototype.getItemUsingIdAsParameter = function(typeName, id, levels, configPath, select) {
	this.getItemById(typeName, id, levels, configPath, select);
};

Aras.prototype.getItemById$skipServerCache = function Aras_getItemById$skipServerCache(typeName, id, levels, select, configPath) {
	/*-- getItemById$skipServerCache
	*
	*   IMPORTANT: This is internal system method. Never use it. Will be removed in future !!!
	*
	*   Method to load an item by id
	*   typeName   = the ItemType name
	*   id         = the id for the item
	*   levels     = the levels deep for the returned item configuration
	*   configPath = the RelationshipType names to include inteh item configuration returned
	*   select     = the list of properties to return
	*
	*/
	if (!id) {
		return null;
	}
	if (levels === undefined) {
		levels = 1;
	}
	if (select === undefined) {
		select = '';
	}
	if (configPath === undefined) {
		configPath = '';
	}

	return this.getItem(typeName, '@id="' + id + '"', '<id>' + id + '</id>', levels, configPath, select);
};

/*-- getItemByName
*
*   Method to load an item by name property
*   typeName   = the ItemType name
*   name       = the name for the item
*   levels     = the levels deep for the returned item configuration
*   configPath = the RelationshipType names to include inteh item configuration returned
*   select     = the list of properties to return
*
*/
Aras.prototype.getItemByName = function(typeName, name, levels, configPath, select) {
	if (levels == undefined) {
		levels = 1;
	}
	return this.getItem(typeName, 'name="' + name + '"', '<name>' + name + '</name>', levels, configPath, select);
};

/*-- getItemByKeyedName
*
*   Method to load an item by keyed_name property
*   typeName   = the ItemType name
*   keyed_name       = the keyed_name for the item
*   levels     = the levels deep for the returned item configuration
*   configPath = the RelationshipType names to include inteh item configuration returned
*   select     = the list of properties to return
*
*/
Aras.prototype.getItemByKeyedName = function(typeName, keyed_name, levels, configPath, select) {
	if (levels == undefined) {
		levels = 0;
	}
	return this.getItem(typeName, 'keyed_name="' + keyed_name + '"', '<keyed_name>' + keyed_name + '</keyed_name>', levels, configPath, select);
};

/*-- getRelationships
*
*   Method to get the Relationships for an item
*   item     = the item
*   typeName = the ItemType name for the Relationships
*
*/
Aras.prototype.getRelationships = function(item, typeName) {
	with (this) {
		if (!item) {
			return false;
		}
		return item.selectNodes('Relationships/Item[@type="' + typeName + '"]');
	}
};

/*-- getKeyedName
*
*   Method to get key field values for an item
*   id = the id for the item
*
*/
Aras.prototype.getKeyedName = function(id, itemTypeName) {
	if (arguments.length < 2) {
		itemTypeName = '';
	}
	if (!id) {
		return '';
	}

	with (this) {
		var item = itemsCache.getItem(id);
		if (!item) {
			item = getItemById(itemTypeName, id, 0);
		}
		if (!item && itemTypeName != '') {
			item = getItemFromServer(itemTypeName, id, 'keyed_name').node;
		}
		if (!item) {
			return '';
		}
		var res = getItemProperty(item, 'keyed_name');
		if (!res) {
			res = getKeyedNameEx(item);
		}
		return res;
	}
};

Aras.prototype.getKeyedNameAttribute = function(node, element) {
	if (!node) {
		return;
	}
	var value;
	var tmpNd = node.selectSingleNode(element);
	if (tmpNd) {
		value = tmpNd.getAttribute('keyed_name');
		if (!value) {
			value = '';
		}
	} else {
		value = '';
	}
	return value;
};

function keyedNameSorter(a, b) {
	var s1 = parseInt(a[0]);
	if (isNaN(s1)) {
		return 1;
	}
	var s2 = parseInt(a[0]);
	if (isNaN(s2)) {
		return -1;
	}

	if (s1 < s2) {
		return -1;
	} else if (s1 == s2) {
		return 0;
	} else {
		return 1;
	}
}

Aras.prototype.sortProperties = function sortProperties(ndsCollection) {
	if (!ndsCollection) {
		return null;
	}

	var tmpArr = new Array();
	for (var i = 0; i < ndsCollection.length; i++) {
		tmpArr.push(ndsCollection[i].cloneNode(true));
	}

	var self = this;
	function sortPropertiesNodes(propNd1, propNd2) {
		var sorder1 = self.getItemProperty(propNd1, 'sort_order');
		if (sorder1 == '') {
			sorder1 = 1000000;
		}
		sorder1 = parseInt(sorder1);
		if (isNaN(sorder1)) {
			return 1;
		}
		var sorder2 = self.getItemProperty(propNd2, 'sort_order');
		if (sorder2 == '') {
			sorder2 = 1000000;
		}
		sorder2 = parseInt(sorder2);
		if (isNaN(sorder2)) {
			return -1;
		}

		if (sorder1 < sorder2) {
			return -1;
		} else if (sorder1 == sorder2) {
			sorder1 = self.getItemProperty(propNd1, 'name');
			sorder2 = self.getItemProperty(propNd2, 'name');
			if (sorder1 < sorder2) {
				return -1;
			} else if (sorder1 == sorder2) {
				return 0;
			} else {
				return 1;
			}
		} else {
			return 1;
		}
	}

	return tmpArr.sort(sortPropertiesNodes);
};

/*-- getItemAllVersions
*
*   Method to load all the versions of an item
*   typeName = the ItemType name
*   id       = the id for the item
*
*/
Aras.prototype.getItemAllVersions = function(typeName, id) {
	with (this) {
		var statusId = showStatusMessage('status', getResource('', 'item_methods.loading_versions', typeName), system_progressbar1_gif);
		var res = soapSend('ApplyItem', '<Item type="' + typeName + '" id="' + id + '" action="getItemAllVersions" />');
		clearStatusMessage(statusId);

		if (res.getFaultCode() != 0) {
			this.AlertError(res);
			return null;
		}

		return res.results.selectNodes(XPathResult('/Item'));
	}
};

/*-- getItemLastVersion
*
*   Method to load the latest version for the item
*   itemTypeName = the ItemType name
*   itemId       = the id for the item
*
*/
Aras.prototype.getItemLastVersion = function(typeName, itemId) {
	var res = this.soapSend('ApplyItem', '<Item type="' + typeName + '" id="' + itemId + '" action="getItemLastVersion" />');
	if (res.getFaultCode() != 0) {
		this.AlertError(res);
		return null;
	}

	return res.results.selectSingleNode(this.XPathResult('/Item'));
}; //getItemLastVersion

/*-- getItemWhereUsed
*
*   Method to load the where used items for an item
*   typeName = the ItemType name
*   id       = the id for the item
*
*/
Aras.prototype.getItemWhereUsed = function(typeName, id) {
	with (this) {
		var statusId = showStatusMessage('status', getResource('', 'item_methods.loading_where_used'), system_progressbar1_gif);
		var res = soapSend('ApplyItem', '<Item type="' + typeName + '" id="' + id + '" action="getItemWhereUsed" />');
		clearStatusMessage(statusId);

		if (res.getFaultCode() != 0) {
			this.AlertError(res);
			return null;
		}
		return res.results.selectSingleNode(XPathResult('/Item'));
	}
};

/*-- getClassWhereUsed
*
*   Method to load the where class is referenced
*   typeId = the ItemType name
*   classId = the id of class node
*		scanTypes = for this types dependencies will be tracked
*		detailed = if true return detailed result, if false return count of dependencies
*
*/
Aras.prototype.getClassWhereUsed = function(typeId, classId, scanTypes, detailed) {
	with (this) {
		var statusId = showStatusMessage('status', getResource('', 'statusbar.getting_impact_data'), '../images/Progress.gif');
		var methodAML =
						'<Item ' + ' type=\'' + this.getItemTypeName(typeId) + '\' ' + ' action=\'GetClassWhereUsed\' >' +
							'<request>' +
								'<class>' + classId + '+</class>' +
								(detailed ? '<verbosity>details</verbosity>' : '') +
								(scanTypes ? '<types>' + scanTypes + '</types>' : '') +
							'</request>' +
						'</Item>';
		var res = applyMethod('GetClassWhereUsed', methodAML);
		clearStatusMessage(statusId);

		var resDom = XmlDocument();
		resDom.loadXML(res);

		return resDom;
	}
};

/*-- getHistoryItems
*
*   Method to load the history items for specified item
*   typeName = the ItemType name
*   id       = the id for the item
*
*/
Aras.prototype.getHistoryItems = function(typeName, id) {
	with (this) {
		var statusId = showStatusMessage('status', getResource('', 'item_methods.loading_history'), system_progressbar1_gif);
		var res = soapSend('ApplyItem', '<Item type="' + typeName + '" id="' + id + '" action="getHistoryItems" />');
		clearStatusMessage(statusId);

		if (res.getFaultCode() != 0) {
			return false;
		}

		var items = res.results.selectNodes(XPathResult('/Item'));

		items = res.results.selectNodes(XPathResult('/Item[@type="History"]'));
		return items;
	}
};

/*-- getItemNextStates
*
*   Method to load the promote values
*   typeName = the ItemType name
*   id       = the id for the item
*
*/
Aras.prototype.getItemNextStates = function(typeName, id) {
	with (this) {
		var res = soapSend('ApplyItem', '<Item type="' + typeName + '" id="' + id + '" action="getItemNextStates" />');

		if (res.getFaultCode() != 0) {
			try {
				var win = windowsByName[id];
				this.AlertError(res, win);
			} catch (excep) {} //callee server is disappeared or ... error
			return null;
		}

		return res.getResult();
	}
};

/*-- promote
*
*   Method to promote an item to the next state
*   typeName  = the ItemType name
*   id        = the id for the item
*   stateName = the next state name
*
*/
Aras.prototype.promote = function Aras_promote(itemTypeName, itemID, stateName, comments) {
	var promoteParams = {
		typeName: itemTypeName,
		id: itemID,
		stateName: stateName,
		comments: comments
	};

	return this.promoteItem_implementation(promoteParams);
};

Aras.prototype.promoteItem_implementation = function Aras_promoteItem_implementation(promoteParams, soapController) {
	var itemTypeName = promoteParams.typeName;
	var itemID = promoteParams.id;
	var stateName = promoteParams.stateName;
	var comments = promoteParams.comments;

	var myItem = this.newIOMItem(itemTypeName, 'promoteItem');
	myItem.setID(itemID);
	myItem.setProperty('state', stateName);

	if (comments) {
		myItem.setProperty('comments', comments);
	}
	//<Item isNew="1" isTemp="1" type="Process Planner" action="promoteItem" id="5D0637227D494B0C84FA8E84221515D0"><state>Baseline</state></Item>

	var msg = itemTypeName + ' to ' + stateName;

	var xml = myItem.dom.xml;

	var async = Boolean(soapController && soapController.callback);

	this.addIdBeingProcessed(itemID, 'promotion of ' + msg);
	var msgId = this.showStatusMessage('status', this.getResource('', 'item_methods.promoting', msg), system_progressbar1_gif);

	var self = this;
	var globalRes = null;
	function afterSoapSend(res) {
		if (msgId) {
			self.clearStatusMessage(msgId);
		}
		self.removeIdBeingProcessed(itemID);

		if (res.getFaultCode() != 0) {
			var win = self.uiFindWindowEx(itemID);
			if (!win) {
				win = window;
			}
			self.AlertError(res, win);
		}

		self.removeFromCache(itemID);
	}

	if (async) {
		var originalCallBack = soapController.callback;
		function afterAsyncSoapSend(soapSendRes) {
			afterSoapSend(soapSendRes);
			originalCallBack(soapSendRes);
		}

		soapController.callback = afterAsyncSoapSend;
	}

	globalRes = this.soapSend('ApplyItem', xml, undefined, undefined, soapController);
	if (async) {
		return null;
	}

	if (globalRes) {
		afterSoapSend(globalRes);
		msgId = this.showStatusMessage('status', this.getResource('', 'item_methods.getting_promote_result'), system_progressbar1_gif);
		globalRes = this.getItemById(itemTypeName, itemID, 0);
		this.clearStatusMessage(msgId);
		if (!globalRes) {
			globalRes = null;
		}
	}

	return globalRes;
};

Aras.prototype.getItemRelationship = function Aras_getItemRelationship(item, relTypeName, relID, useServer) {
	if (!item || !relTypeName || !relID || useServer == undefined) {
		return null;
	}

	var res = item.selectSingleNode('Relationships/Item[@type="' + relTypeName + '" and @id="' + relID + '"]');
	if (res) {
		return res;
	}
	if (!useServer) {
		return null;
	}

	var itemID = item.getAttribute('id');
	var bodyStr = '<source_id >' + itemID + '</source_id>' + '<id >' + relID + '</id>';
	var xpath = '@id=\'' + relID + '\' and source_id=\'' + itemID + '\'';
	res = this.getItem(relTypeName, xpath, bodyStr, 0);

	with (this) {
		if (res != null || res != undefined) {
			if (!item.selectSingleNode('Relationships')) {
				item.appendChild(item.ownerDocument.createElement('Relationships'));
			}
			res = res.selectSingleNode('//Item[@type="' + relTypeName + '" and @id="' + relID + '"]');
			if (!res) {
				return null;
			}
			res = item.selectSingleNode('Relationships').appendChild(res);
			return res;
		} else {
			return null;
		}
	}
};

Aras.prototype.getItemRelationships = function(itemTypeName, itemId, relsName, pageSize, page, body, forceReplaceByItemFromServer) {
	if (!(itemTypeName && itemId && relsName)) {
		return null;
	}
	if (pageSize == undefined) {
		pageSize = '';
	}
	if (page == undefined) {
		page = '';
	}
	if (body == undefined) {
		body = '';
	}
	if (forceReplaceByItemFromServer == undefined) {
		forceReplaceByItemFromServer = false;
	}

	var res = null;
	with (this) {
		var itemNd = getItemById(itemTypeName, itemId, 0);
		if (!itemNd) {
			return null;
		}

		if (!forceReplaceByItemFromServer && (pageSize == -1 || isTempID(itemId) || (itemNd.getAttribute('levels') && parseInt(itemNd.getAttribute('levels')) > 0))) {

			if (!isNaN(parseInt(pageSize)) && parseInt(pageSize) > 0 && !isNaN(parseInt(page)) && parseInt(page) > -1) {
				res = itemNd.selectNodes('Relationships/Item[@type="' + relsName + '" and @page="' + page + '"]');
				if (res && res.length == pageSize) {
					return res;
				}
			} else {
				res = itemNd.selectNodes('Relationships/Item[@type="' + relsName + '"]');
				if (res && res.length > 0) {
					return res;
				}
			}
		}

		var bodyStr = '<Item type="' + itemTypeName + '" id="' + itemId + '" relName="' + relsName + '" action="getItemRelationships" ';
		if (pageSize) {
			bodyStr += ' pagesize="' + pageSize + '"';
		}
		if (page) {
			bodyStr += ' page="' + page + '"';
		}
		if (body == '') {
			bodyStr += '/>';
		} else {
			bodyStr += '>' + body + '</Item>';
		}

		var statusId = showStatusMessage('status', getResource('', 'item_methods.loading_relationships', itemTypeName), system_progressbar1_gif);
		var res = soapSend('ApplyItem', bodyStr);
		clearStatusMessage(statusId);

		if (res.getFaultCode() != 0) {
			this.AlertError(res);
			return null;
		}

		if (!itemNd.selectSingleNode('Relationships')) {
			createXmlElement('Relationships', itemNd);
		}
		var rels = res.results.selectNodes(XPathResult('/Item[@type="' + relsName + '"]'));
		var itemRels = itemNd.selectSingleNode('Relationships');
		var ids = new Set();
		for (var i = 0; i < rels.length; i++) {
			var rel = rels[i].cloneNode(true);
			var relId = rel.getAttribute('id');
			ids.add(relId);
			var prevRel = itemRels.selectSingleNode('Item[@type="' + relsName + '" and @id="' + relId + '"]');
			if (prevRel) {
				if (forceReplaceByItemFromServer == true) {
					// By some reason the previous implementation did not replaced existing on the node
					// relationships with the new relationships obtained from the server but rather
					// just removed some attributes on them (like "pagesize", etc.). From other side those
					// relationships that don't exist on the 'itemNd' are added to it. This is wrong as
					// the newly obtained relationships even if they already exist on 'itemNd' might have
					// some properties that are different in db from what is in the client memory.
					// NOTE: the fix will break the case when the client changes some relationship properties
					//       in memory and then calls this method expecting that these properties will stay unchanged,
					//       but: a) this method seems to be called only from getFileURLEx(..); b) if the above
					//       behavior is expected then another method is probably required which must be called
					//       something like 'mergeRelationships'.
					// by Andrey Knourenko
					itemRels.removeChild(prevRel);
				} else {
					this.mergeItem(prevRel, rel);
					continue;
				}
			}
			itemRels.appendChild(rel);
		}
		itemNd.setAttribute('levels', '0');
		if (ids.size === 0) {
			return null;
		}

		res = ArasModules.xml.selectNodes(itemRels, 'Item[@type="' + relsName + '"]').filter(function(relNode) {
			return ids.has(relNode.getAttribute('id'));
		});
	} //with (this)

	return res;
};

Aras.prototype.resetLifeCycle = function Aras_resetLifeCycle(itemTypeName, itemID) {
	if (!itemTypeName || !itemID) {
		return false;
	}

	with (this) {
		var statusId = showStatusMessage('status', getResource('', 'item_methods.reseting_life_cycle_state'), system_progressbar1_gif);
		var bodyStr = '<Item type="' + itemTypeName + '" id="' + itemID + '" action="resetLifecycle"/>';
		var res = soapSend('ApplyItem', bodyStr);
		clearStatusMessage(statusId);

		if (res.getFaultCode() != 0) {
			var win = uiFindWindowEx(itemID);
			if (!win) {
				win = window;
			}
			this.AlertError(res, win);
			return false;
		}

		var itemNd = res.results.selectSingleNode(XPathResult('/Item'));
		if (!itemNd) {
			return false;
		}

		return true;
	}
};

Aras.prototype.setDefaultLifeCycle = function setDefaultLifeCycle(itemTypeName, itemID) {
	if (!itemTypeName || !itemID) {
		return false;
	}

	var statusId = this.showStatusMessage('status', this.getResource('', 'item_methods.reseting_life_cycle_state'), system_progressbar1_gif);
	var bodyStr = '<Item type="' + itemTypeName + '" id="' + itemID + '" action="setDefaultLifecycle"/>';
	var res = this.soapSend('ApplyItem', bodyStr);
	this.clearStatusMessage(statusId);
	if (res.getFaultCode() != 0) {
		var win = this.uiFindWindowEx(itemID);
		if (!win) {
			win = window;
		}
		this.AlertError(res, win);
		return false;
	}
	var faultStr = res.getFaultString();
	if (faultStr != '') {
		return false;
	}
	this.removeFromCache(itemID);
	var itemNd = this.getItemById(itemTypeName, itemID, 0);
	if (!itemNd) {
		return false;
	}

	return true;
};

Aras.prototype.resetItemAccess = function(itemTypeName, itemId) {
	if (itemTypeName == undefined || itemId == undefined) {
		return false;
	}

	with (this) {
		var itemNd = null;
		if (itemTypeName == '') {
			itemNd = getItemById('', itemId, 0);
			if (!itemNd) {
				return false;
			}
			itemTypeName = itemNd.getAttribute('type');
		}

		var statusId = showStatusMessage('status', getResource('', 'item_methods.reseting_item_access'), system_progressbar1_gif);
		var bodyStr = '<Item type="' + itemTypeName + '" id="' + itemId + '" action="resetItemAccess"/>';
		var res = soapSend('ApplyItem', bodyStr);
		clearStatusMessage(statusId);

		try {
			var winBN = windowsByName[itemId];
			if (res.getFaultCode() != 0) {
				this.AlertError(res, winBN);
				return false;
			}
		} catch (excep) {} //callee server is disappeared or ... error
		var tempRes = loadItems(itemTypeName, 'id="' + itemId + '"', 0);
		if (tempRes) {
			return true;
		} else {
			return false;
		}
	}
};

Aras.prototype.resetAllItemsAccess = function(itemTypeName) {
	if (!itemTypeName) {
		return false;
	}

	with (this) {
		var statusId = showStatusMessage('status', getResource('', 'item_methods.reseting_item_access'), system_progressbar1_gif);
		var bodyStr = '<Item type="' + itemTypeName + '" action="resetAllItemsAccess"/>';
		var res = soapSend('ApplyItem', bodyStr);
		clearStatusMessage(statusId);

		if (res.getFaultCode() != 0) {
			this.AlertError(res);
			return false;
		}

		return true;
	}
};

Aras.prototype.populateRelationshipsGrid = function Aras_populateRelationshipsGrid(bodyStr) {
	if (!bodyStr) {
		return null;
	}

	with (this) {
		var statusId = showStatusMessage('status', getResource('', 'item_methods.populating_relationships_grid'), system_progressbar1_gif);
		var res = soapSend('PopulateRelationshipsGrid', bodyStr);
		clearStatusMessage(statusId);

		if (res.getFaultCode() != 0) {
			AlertError(res);
		}

		return res;
	}
};

Aras.prototype.populateRelationshipsTables = function(bodyStr) {
	if (!bodyStr) {
		return null;
	}

	with (this) {
		var statusId = showStatusMessage('status', getResource('', 'item_methods.populating_relationships_tables'), system_progressbar1_gif);
		var res = soapSend('PopulateRelationshipsTables', bodyStr);
		clearStatusMessage(statusId);

		if (res.getFaultCode() != 0) {
			AlertError(res);
			return null;
		}

		return res.results.selectSingleNode('//tables');
	}
};

Aras.prototype.getPermissions = function(access_type, itemID, typeID, typeName) {
	if (!(access_type && itemID)) {
		return false;
	}
	if (access_type === 'can_add') {
		const itemType = this.getItemTypeForClient(itemID, 'id').node;
		if (this.getItemProperty(itemType, 'is_dependent') == '1') {
			return false;
		}
		const isRelationshipAndUseSrcAccess = this.getItemProperty(itemType, 'is_relationship') == '1' && this.getItemProperty(itemType, 'user_src_access') == '1';
		if (isRelationshipAndUseSrcAccess) {
			return false;
		}
		const currentUserIdentityList = aras.getIdentityList();
		const isSuperUser = currentUserIdentityList.indexOf('6B14D33C4A7D41C188CCF2BC15BD01A3') > -1;
		if (isSuperUser) {
			return true;
		}

		const canAddIdentities = itemType.selectNodes('Relationships/Item[@type="Can Add" and (can_add = "1") and (string(class_path) = "" or class_path = "/" or class_path = "*")]/related_id');

		for (let i = 0; i < canAddIdentities.length; i++) {
			const canAddIdentity = canAddIdentities[i];
			if (currentUserIdentityList.indexOf(canAddIdentity.text) > -1) {
				return true;
			}
		}
		return false;
	}

	with (this) {
		var bodyStr = '<Item id="' + itemID + '" access_type="' + access_type + '" action="getPermissions" ';
		if ((typeID != undefined) && typeID) {
			bodyStr += ' typeId="' + typeID + '"';
		}
		if ((typeName != undefined) && typeName) {
			bodyStr += ' type="' + typeName + '"';
		}
		bodyStr += '/>';

		var statusId = showStatusMessage('status', getResource('', 'item_methods.getting_permissions_right'), system_progressbar1_gif);
		var res = soapSend('ApplyItem', bodyStr);
		clearStatusMessage(statusId);

		if (res.getFaultCode() != 0) {
			AlertError(res);
			return null;
		}

		return (res.getResult().text == '1');
	}
};

Aras.prototype.getRealPropertyForForeignProperty = function Aras_getRealPropertyForForeignProperty(foreignProperty, currentItemType) {
	function getPropertyByCriteria(itemType, criteriaName, criteriaValue) {
		if (null == itemType) {
			return null;
		}

		return itemType.selectSingleNode('Relationships/Item[@type=\'Property\' and ' + criteriaName + '=\'' + criteriaValue + '\']');
	}

	if ('foreign' !== this.getItemProperty(foreignProperty, 'data_type')) {
		return foreignProperty;
	}

	if (null == currentItemType) {
		currentItemType = this.getItemTypeDictionary(this.getItemProperty(foreignProperty, 'source_id'), 'id').node;
	}

	var sourceProp = getPropertyByCriteria(currentItemType, 'id', this.getItemProperty(foreignProperty, 'data_source'));
	var foreignItemType = this.getItemTypeDictionary(this.getItemProperty(sourceProp, 'data_source'), 'id').node;

	var result = getPropertyByCriteria(foreignItemType, 'id', foreignProperty.selectSingleNode('foreign_property').text);
	if ('foreign' == this.getItemProperty(result, 'data_type')) {
		result = this.getRealPropertyForForeignProperty(result, foreignItemType);
	}

	return result;
};

Aras.prototype.getPropertiesOfTypeFile = function Aras_getPropertiesOfTypeFile(ItemTypeNd) {
	/*
	this function is for internal use *** only ***.
	----
	ItemTypeNd - node of ItemType
	*/
	var FileIT_ID_const = this.getFileItemTypeID();
	var fileProps = ItemTypeNd.selectNodes('Relationships/Item[@type=\'Property\' and data_type=\'item\' and data_source=\'' + FileIT_ID_const + '\' ' + 'and name!=\'related_id\' and name!=\'config_id\']');
	/*
	related_id property is ignored here to not treat related_id as a property of relationship (for checkout/checkin) (IR-006449)
	config_id property is ignored here to fix IR-006448 (to enable subsequent checkins. to do this all file instances must be locked.
	but config_id points to first generation and thus if current generation is 2 or greater checkin is not available)

	ItemType File has 2 properties of type File: id and config_id.
	This allows user to perform checkin/checkout in context of File instances.
	This looks like a logic bug, but there are solutions wich rely on this. (PLM for example)
	*/

	return fileProps;
};

/*-- applyItemWithFilesCheck
*
*   Method to ApplyItem. Checking "do files exist in itemNd" is called before soap send. Returns xml node.
*   itemNd           = xml node to send in ApplyItem soap action. May contain items with type="File".
*   win             = item window
*   statusMsg       = message text to show in status bar. If empty then nothing is shown.
*   XPath2ReturnedNd = xpath to select returned node. Default: aras.XPathResult('/Item')
*
*/
Aras.prototype.applyItemWithFilesCheck = function Aras_applyItemWithFilesCheck(itemNd, win, statusMsg, XPath2ReturnedNd) {
	if (!XPath2ReturnedNd) {
		XPath2ReturnedNd = this.XPathResult('/Item');
	}

	var res;
	var files = itemNd.selectNodes('descendant-or-self::Item[@type="File" and (@action="add" or @action="update")]');

	var statusId;
	if (statusMsg) {
		statusId = this.showStatusMessage('status', statusMsg, system_progressbar1_gif);
	}
	if (files.length == 0) {
		res = this.soapSend('ApplyItem', itemNd.xml);
	} else {
		res = this.soapSend('generateNewGUID', '');
	}
	if (res.getFaultCode() != 0) {
		this.AlertError(res, win);
		res = null;
	} else {
		if (files.length == 0) {
			res = res.results.selectSingleNode(XPath2ReturnedNd);
		} else {
			res = this.sendFilesWithVaultApplet(itemNd, statusMsg, XPath2ReturnedNd);
		}
	}
	if (statusId) {
		this.clearStatusMessage(statusId);
	}
	return res;
};

Aras.prototype.applyItemWithFilesCheckAsync = function Aras_applyItemWithFilesCheckAsync(itemNd, win, statusMsg, XPath2ReturnedNd, isGridUpdate) {
	if (!XPath2ReturnedNd) {
		XPath2ReturnedNd = this.XPathResult('/Item');
	}

	var res;
	var promise;
	var files = itemNd.selectNodes('descendant-or-self::Item[@type="File" and (@action="add" or @action="update")]');

	var statusId;
	if (statusMsg) {
		statusId = this.showStatusMessage('status', statusMsg, system_progressbar1_gif);
	}
	if (files.length == 0) {
		res = this.soapSend('ApplyItem', itemNd.xml, '', isGridUpdate);
	} else {
		res = this.soapSend('generateNewGUID', '');
	}
	if (res.getFaultCode() != 0) {
		this.AlertError(res, win);
		promise = Promise.resolve(null);
	} else {
		if (files.length == 0) {
			promise = Promise.resolve(res.results.selectSingleNode(XPath2ReturnedNd));
		} else {
			promise = this.sendFilesWithVaultAppletAsync(itemNd, statusMsg, XPath2ReturnedNd);
		}
	}

	return promise.then(function(res) {
				if (statusId) {
					this.clearStatusMessage(statusId);
				}
				return res;
			}.bind(this));
};

/** item_methodsEx.js **/
// © Copyright by Aras Corporation, 2004-2012.

/*
*   The item extended methods extension for the Aras Object.
*   methods in this file use xml nodes as parameters
*/

/// <reference path="soap_object.js" />

Aras.prototype.isNew = function(itemNd) {
	if (!this.isTempEx(itemNd)) {
		return false;
	}
	return ('add' == itemNd.getAttribute('action'));
};

Aras.prototype.isTempEx = function(itemNd) {
	if (!itemNd) {
		return undefined;
	}
	return (itemNd.getAttribute('isTemp') == '1');
};

Aras.prototype.isDirtyEx = function(itemNd) {
	if (!itemNd) {
		return undefined;
	}
	return (itemNd.selectSingleNode('descendant-or-self::Item[@isDirty="1"]') !== null);
};

Aras.prototype.isEditStateEx = function(itemNd) {
	if (!itemNd) {
		return false;
	}

	return this.isTempEx(itemNd) || itemNd.getAttribute('isEditState') === '1'; 
};

Aras.prototype.setItemEditStateEx = function(itemNd, state) {
	if (!itemNd) {
		return;
	}

	itemNd.setAttribute('isEditState', state ? '1' : '0');
};

Aras.prototype.isLocked = function Aras_isLocked(itemNd) {
	if (this.isTempEx(itemNd)) {
		return false;
	}
	return ('' !== this.getItemProperty(itemNd, 'locked_by_id'));
};

Aras.prototype.isLockedByUser = function Aras_isLockedByUser(itemNd) {
	if (this.isTempEx(itemNd)) {
		return false;
	}

	var locked_by_id = this.getItemProperty(itemNd, 'locked_by_id');
	return (locked_by_id == this.getCurrentUserID());
};

/*-- copyItemEx
*
*   Method to copy an item
*   itemNd = item to be cloned
*
*/
Aras.prototype.copyItemEx = function(itemNd, action, do_add) {
	if (!itemNd) {
		return false;
	}
	if (!action) {
		action = 'copyAsNew';
	}
	if (do_add === undefined || do_add === null) {
		do_add = true;
	}

	var itemTypeName = itemNd.getAttribute('type');
	var bodyStr = '<Item type="' + itemTypeName + '" id="' + itemNd.getAttribute('id') + '" ';
	if (itemTypeName.search(/^ItemType$|^RelationshipType$|^User$/) === 0) {
		bodyStr += ' action="copy" ';
	} else {
		bodyStr += ' action="' + action + '" ';
	}
	if (!do_add) {
		bodyStr += ' do_add="0" ';
	}
	bodyStr += ' />';

	var res = null;

	var statusId = this.showStatusMessage('status', this.getResource('', 'common.copying_item'), system_progressbar1_gif);
	res = this.soapSend('ApplyItem', bodyStr);
	this.clearStatusMessage(statusId);

	var faultCode = res.getFaultCode();
	if (faultCode !== 0 && faultCode !== '0') {
		this.AlertError(res);
		return null;
	}

	var itemCopy = res.results.selectSingleNode('//Item');
	return itemCopy;
};

//+++++ saving item +++++
Aras.prototype.checkItemType = function(itemNd, win) {
	var isTaskOrItsChildCache;
	function isDataSourceSpecified(arasObj) {
		var isTaskOrItsChild = itemNd && (arasObj.getItemProperty(itemNd, 'name') == 'InBasket Task' || itemNd.selectSingleNode('../../../../../Item[name=\'InBasket Task\']'));
		if (!isTaskOrItsChild) {
			if (isTaskOrItsChildCache === undefined) {
				var tmpRes = arasObj.applyItem(
					'<Item type=\'Morphae\' action=\'get\' select=\'id\'>' +
					'<source_id><Item type=\'ItemType\'><keyed_name>InBasket Task</keyed_name></Item></source_id>' +
					'<related_id>' + itemNd.getAttribute('id') + '</related_id>' +
					'</Item>');
				if (tmpRes) {
					var tmpDoc = arasObj.createXMLDocument();
					tmpDoc.loadXML(tmpRes);
					tmpRes = tmpDoc.selectSingleNode('//Item') ? true : false;
				} else {
					tmpRes = false;
				}
				isTaskOrItsChildCache = tmpRes;
			}
			isTaskOrItsChild = isTaskOrItsChildCache;
		}

		if (!propDs && propName != 'related_id' && propName != 'source_id' && !isTaskOrItsChild) {
			arasObj.AlertError(arasObj.getResource('', 'item_methods_ex.property_data_source_not_specified', propKeyedName));
			return false;
		} else {
			return true;
		}
	}

	var name = this.getItemProperty(itemNd, 'name');
	if (name === '') {
		this.AlertError(this.getResource('', 'item_methods_ex.item_type_name_cannot_be_blank'), '', '', win);
		return false;
	}

	var property, propKeyedName, propDt, propName, propDs, tmpStoredLength, storedLength, pattern;

	var properties = itemNd.selectNodes('Relationships/Item[@type="Property" and (not(@action) or (@action!="delete" and @action!="purge"))]');
	var i;
	for (i = 0; i < properties.length; i++) {
		property = properties[i];
		propKeyedName = this.getKeyedNameEx(property);

		propName = this.getItemProperty(property, 'name');
		if (!propName) {
			this.AlertError(this.getResource('', 'item_methods_ex.item_type_has_property_with_no_name', this.getItemProperty(itemNd, 'label')), win);
			return false;
		}

		propDt = this.getItemProperty(property, 'data_type');
		propDs = this.getItemProperty(property, 'data_source');

		if (propDt == 'string' || propDt == 'ml_string' || propDt == 'mv_list') {
			tmpStoredLength = this.getItemProperty(property, 'stored_length');
			storedLength = parseInt(tmpStoredLength);

			if (isNaN(storedLength)) {
				this.AlertError(this.getResource('', 'item_methods_ex.length_of_property_not_specified', propKeyedName), '', '', win);
				return false;
			} else if (storedLength <= 0) {
				this.AlertError(this.getResource('', 'item_methods_ex.length_of_property_invalid', propKeyedName, tmpStoredLength), '', '', win);
				return false;
			}

			if ('mv_list' == propDt && !isDataSourceSpecified(this)) {
				return false;
			}
		} else if ((propDt == 'item' || propDt == 'list' || propDt == 'filter list' || propDt == 'color list' || propDt == 'sequence' || propDt == 'foreign') && !isDataSourceSpecified(this)) {
			return false;
		} else if (propDt == 'filter list') {
			if (!isDataSourceSpecified(this)) {
				return false;
			}

			pattern = this.getItemProperty(property, 'pattern');
			if (!pattern) {
				this.AlertError(this.getResource('', 'item_methods_ex.fliter_list_property_has_to_have_pattern', propKeyedName), '', '', win);
				return false;
			}

			var tmpNd_1 = itemNd.selectSingleNode('Relationships/Item[@type="Property" and name="' + pattern + '" and (not(@action) or (@action!="delete" and @action!="purge"))]');
			if (!tmpNd_1) {
				this.AlertError(this.getResource('', 'item_methods_ex.filter_list_property_has_wrong_pattern', propKeyedName, pattern), win);
				return false;
			} else if (this.getItemProperty(tmpNd_1, 'name') == this.getItemProperty(property, 'name')) {
				this.AlertError(this.getResource('', 'item_methods_ex.property_for_pattern_cannot_property_itself', propKeyedName), '', '', win);
				return false;
			}
		}
	}
	var discussionTemplates = itemNd.selectNodes('Relationships/Item[@type="DiscussionTemplate" and (not(@action) or (@action!="delete" and @action!="purge"))]');
	if (discussionTemplates.length > 0) {
		var isRootClassificationExists = false;
		for (i = 0; i < discussionTemplates.length; i++) {
			var discussionTemplate = discussionTemplates[i];
			if (this.getItemProperty(discussionTemplate, 'class_path') === '') {
				isRootClassificationExists = true;
			}
		}
		if (!isRootClassificationExists) {
			this.AlertError(this.getResource('', 'item_methods_ex.item_type_should_have_discussiontemplate_for_root_class_path', propKeyedName, pattern), win);
			return isRootClassificationExists;
		}
	}

	return true;
};

Aras.prototype.checkItemForErrors = function Aras_checkItemForErrors(itemNd, exclusion, itemType, breakOnFirstError, emptyPropertyWithDefaultValueCallback) {
	var resultErrors = [];

	var propNd, reqId, isRequired, reqName, reqDataType, itemPropVal, defVal;

	var typeOfItem = itemNd.getAttribute('type');
	if (!typeOfItem) {
		return resultErrors;
	}

	itemType = itemType ? itemType : this.getItemTypeDictionary(typeOfItem).node;
	if (!itemType) {
		return resultErrors;
	}

	var propertiesXpath = 'Relationships/Item[@type="Property" and (is_required="1" or data_type="string")' + (exclusion ? ' and name!="' + exclusion + '"' : '') + ']';
	var requirements = itemType.selectNodes(propertiesXpath);
	for (var i = 0; i < requirements.length; i++) {
		propNd = requirements[i];
		reqId = propNd.getAttribute('id');
		reqName = this.getItemProperty(propNd, 'name');
		reqDataType = this.getItemProperty(propNd, 'data_type');
		isRequired = (this.getItemProperty(propNd, 'is_required') == '1');

		if (!reqName) {
			var noNameError = this.getResource('', 'item_methods_ex.item_type_has_property_with_no_name', this.getItemProperty(itemType, 'label'));
			resultErrors.push({ message: noNameError });
			if (breakOnFirstError) {
				return resultErrors;
			}
		}

		var proplabel = this.getItemProperty(propNd, 'label');
		if (!proplabel) {
			proplabel = this.getItemProperty(propNd, 'keyed_name');
		}
		if (!proplabel) {
			proplabel = '';
		}

		itemPropVal = this.getItemProperty(itemNd, reqName);
		if (isRequired && itemPropVal === '') {
			defVal = this.getItemProperty(propNd, 'default_value');
			if (defVal) {
				if (emptyPropertyWithDefaultValueCallback && typeof(emptyPropertyWithDefaultValueCallback) === 'function') {
					var callbackResult = emptyPropertyWithDefaultValueCallback(itemNd, reqName, proplabel, defVal);
					if (!callbackResult.result) {
						if (callbackResult.message) {
							resultErrors.push({ message: callbackResult.message });
						} else {
							resultErrors.push({});
						}
						if (breakOnFirstError) {
							return resultErrors;
						}
					}
				}
				continue;
			} else if (!this.isPropFilledOnServer(reqName) && (reqDataType != 'md5' || itemNd.getAttribute('action') == 'add' || itemNd.selectSingleNode(reqName))) {
				var fieldRequiredError = this.getResource('', 'item_methods_ex.field_required_provide_value', proplabel);
				resultErrors.push({ message: fieldRequiredError });
				if (breakOnFirstError) {
					return resultErrors;
				}
			}
		}

		if (reqDataType == 'string') {
			var storedLength = parseInt(this.getItemProperty(propNd, 'stored_length'));
			if (!isNaN(storedLength) && itemPropVal.length - storedLength > 0) {
				var maxLengthError = this.getResource('', 'item_methods_ex.maximum_length_characters_for_property', proplabel, storedLength, itemPropVal.length);
				resultErrors.push({ message: maxLengthError });
				if (breakOnFirstError) {
					return resultErrors;
				}
			}
		}

	}

	return resultErrors;
};

Aras.prototype.checkItem = function Aras_checkItem(itemNd, win, exclusion, itemType) {
	var self = this;
	var defaultFieldCheckCallback = function(itemNode, reqName, proplabel, defVal) {
		var ask = self.confirm(self.getResource('', 'item_methods_ex.field_required_default_will_be_used', proplabel, defVal));
		if (ask) {
			self.setItemProperty(itemNode, reqName, defVal);
		}
		return {result: ask, message: ''};
	};

	var errors = this.checkItemForErrors(itemNd, exclusion, itemType, true, defaultFieldCheckCallback);
	if (errors.length > 0) {
		if (errors[0].message) {
			this.AlertError(errors[0].message);
		}
	}
	return errors.length === 0;
};

Aras.prototype.prepareItem4Save = function Aras_prepareItem4Save(itemNd) {
	var itemTypeName = itemNd.getAttribute('type');
	var itemID, item, items, items2;
	var i, j, parentNd;

	itemID = itemNd.getAttribute('id');
	items = itemNd.selectNodes('.//Item[@id="' + itemID + '"]');

	for (i = 0; i < items.length; i++) {
		item = items[i];
		parentNd = item.parentNode;
		parentNd.removeChild(item);
		parentNd.text = itemID;
	}

	items = itemNd.selectNodes('.//Item[@action="delete"]');
	for (i = 0; i < items.length; i++) {
		item = items[i];
		var childs = item.selectNodes('*[count(descendant::Item[@action])=0]');
		for (j = 0; j < childs.length; j++) {
			var childItem = childs[j];
			item.removeChild(childItem);
		}
	}

	items = itemNd.selectNodes('.//Item');
	for (i = 0; i < items.length; i++) {
		item = items[i];
		itemID = item.getAttribute('id');
		items2 = itemNd.selectNodes('.//Item[@id="' + itemID + '"][@data_type != "foreign"]');
		for (j = 1; j < items2.length; j++) {
			item = items2[j];
			parentNd = item.parentNode;
			parentNd.removeChild(item);
			parentNd.text = itemID;
		}
	}

	items = itemNd.selectNodes('.//Item[not(@action) and not(.//Item/@action)]');
	for (i = 0; i < items.length; i++) {
		items[i].setAttribute('action', 'get');
	}

	items = itemNd.selectNodes('.//Item[@action="get" and (not(.//Item) or not(.//Item/@action!="get"))]');
	for (i = 0; i < items.length; i++) {
		item = items[i];
		itemID = item.getAttribute('id');
		parentNd = item.parentNode;

		if (parentNd.nodeName == 'Relationships') {
			parentNd.removeChild(item);
		} else {
			if (itemID) {
				parentNd.removeChild(item);
				parentNd.text = itemID;
			}
		}
	}

	items = itemNd.selectNodes('.//Item[@action="get"]');
	for (i = 0; i < items.length; i++) {
		items[i].setAttribute('action', 'skip');
	}
};

function ClearDependenciesInMetadataCache(aras, itemNd) {
	var xPropertyContainerItemIT = '2073428E99384916938E3519AF1C0A44';

	var items = itemNd.selectNodes('descendant-or-self::Item');
	for (var i = 0; i < items.length; i++) {
		var tmpId = items[i].getAttribute('id');
		if (tmpId) {
			aras.MetadataCache.RemoveItemById(tmpId);
		}
	}
	var srcId = aras.getItemProperty(itemNd, 'source_id');
	if (srcId) {
		aras.MetadataCache.RemoveItemById(srcId);
	}
	//calling new method to clear metadata dates in Cache if Item has certain type
	var NeedClearCache = itemNd.getAttribute('type');
	if (NeedClearCache == 'ItemType' || NeedClearCache == 'Property' || NeedClearCache == 'Grid Event' || NeedClearCache == 'View' || NeedClearCache == 'TOC View' || NeedClearCache == 'Item Action' || NeedClearCache == 'Item Report' ||
			NeedClearCache == 'Client Event' || NeedClearCache == 'Morphae' || NeedClearCache == 'RelationshipType' || NeedClearCache == 'Relationship View' || NeedClearCache == 'Relationship Grid Event' ||
			NeedClearCache == 'Can Add' || NeedClearCache == 'History Template' || NeedClearCache == 'History Template Action' || NeedClearCache == 'History Action' || NeedClearCache === 'ItemType_xPropertyDefinition' || NeedClearCache === 'xPropertyDefinition') {

		aras.MetadataCache.DeleteITDatesFromCache();// if saving IT - remove all IT dates from cache, form dates can stay
	}

	if (NeedClearCache == 'ItemType' || NeedClearCache == 'RelationshipType' || NeedClearCache == 'Relationship View' || NeedClearCache == 'Relationship Grid Event') {
		aras.MetadataCache.DeleteRTDatesFromCache();
	}

	if (NeedClearCache == 'Identity') {
		aras.MetadataCache.DeleteITDatesFromCache();
		aras.MetadataCache.DeleteIdentityDatesFromCache();
	}

	//If node isn't not part of ItemType, but List - remove List dates from cache
	if (NeedClearCache == 'List' || NeedClearCache == 'Value' || NeedClearCache == 'Filter Value') {
		aras.MetadataCache.DeleteListDatesFromCache();
	}

	//If node isn't not part of ItemType nor List but Form - remove Form and IT dates from cache
	//hack: When new ItemType is being created server creates for it new form using "Create Form for ItemType" server method. To update form cache ItemType variant is being added.
	if (NeedClearCache == 'Form' || NeedClearCache == 'Form Event' || NeedClearCache == 'Method' || NeedClearCache == 'Body' || NeedClearCache == 'Field' || NeedClearCache == 'Field Event' || NeedClearCache == 'Property' || NeedClearCache == 'List' || NeedClearCache == 'ItemType') {
		aras.MetadataCache.DeleteFormDatesFromCache();
		aras.MetadataCache.DeleteITDatesFromCache();//remove IT dates on saving Form, since it affects IT
		aras.MetadataCache.DeleteClientMethodDatesFromCache();
		aras.MetadataCache.DeleteAllClientMethodsDatesFromCache();

		aras.MetadataCache.RemoveItemById(xPropertyContainerItemIT);
	}

	//If node is searchMode, remove SearchMode dates from cache
	if (NeedClearCache == 'SearchMode') {
		aras.MetadataCache.DeleteSearchModeDatesFromCache();
	}

	var _needClearCache = ',' + (NeedClearCache || '').toLowerCase() + ',';
	if (',globalpresentationconfiguration,itpresentationconfiguration,presentationconfiguration,presentationcommandbarsection,commandbarsection,commandbarsectionitem,commandbaritem,'.indexOf(_needClearCache) > -1  || NeedClearCache === 'Report' || NeedClearCache === 'Action') {
		aras.MetadataCache.DeleteConfigurableUiDatesFromCache();
	}
	if (',presentationconfiguration,presentationcommandbarsection,'.indexOf(_needClearCache) > -1) {
		aras.MetadataCache.DeletePresentationConfigurationDatesFromCache();
	}

	if (NeedClearCache === 'CommandBarSection') {
		aras.MetadataCache.DeleteCommandBarSectionDatesFromCache();
	}
	if (NeedClearCache == 'ItemType' || NeedClearCache === 'cmf_ContentType') {
		aras.MetadataCache.DeleteContentTypeByDocumentItemTypeDatesFromCache();
		aras.MetadataCache.DeleteITDatesFromCache();//remove IT dates on saving ContentType, since it affects a lot of IT
	}
	if (NeedClearCache === 'xClassificationTree' || NeedClearCache === 'xClass' || NeedClearCache === 'xClass_xPropertyDefinition' ||
		NeedClearCache === 'xPropertyDefinition' || NeedClearCache === 'xClassificationTree_ItemType') {
		aras.MetadataCache.DeleteXClassificationTreesDates();
		aras.MetadataCache.DeleteITDatesFromCache();
		if (NeedClearCache === 'xClassificationTree') {
			var xItemTypes = aras.getItemRelationshipsEx(itemNd, 'xClassificationTree_ItemType');
			if (xItemTypes) {
				Array.prototype.forEach.call(xItemTypes, function(item) {
					var itemType = item.selectSingleNode('related_id/Item');
					aras.MetadataCache.RemoveItemById(aras.getItemProperty(itemType, 'id'));
				});
			}
		}

		aras.MetadataCache.RemoveItemById(xPropertyContainerItemIT);
	}

	if (NeedClearCache === 'cui_WindowSection' || NeedClearCache === 'cui_Control') {
		aras.MetadataCache.DeleteConfigurableUiControlsDatesFromCache();
	}
}

Aras.prototype.calcMD5 = function(s) {
	return calcMD5(s);
};

(function(){
	function _sendFilesWithVaultAppletBefore(itemNd, statusMsg, XPath2ReturnedNd) {
		var win = this.uiFindWindowEx2(itemNd);
		if (!XPath2ReturnedNd) {
			XPath2ReturnedNd = this.XPathResult('/Item');
		}

		var vaultServerURL = this.getVaultServerURL();
		var vaultServerID = this.getVaultServerID();
		if (vaultServerURL === '' || vaultServerID === '') {
			this.AlertError(this.getResource('', 'item_methods_ex.vault_sever_not_specified'), '', '', win);
			return null;
		}

		var vaultApplet = this.vault;
		vaultApplet.clearClientData();
		vaultApplet.clearFileList();

		var headers = this.getHttpHeadersForSoapMessage('ApplyItem');
		headers['VAULTID'] = vaultServerID;
		for (var hName in headers) {
			vaultApplet.setClientData(hName, headers[hName]);
		}

		var fileNds = itemNd.selectNodes('descendant-or-self::Item[@type="File" and (@action="add" or @action="update")]');
		for (var i = 0; i < fileNds.length; i++) {
			var fileNd = fileNds[i];
			var fileID = fileNd.getAttribute('id');

			if (fileID) {
				var fileRels = fileNd.selectSingleNode('Relationships');
				if (!fileRels) {
					fileRels = this.createXmlElement('Relationships', fileNd);
				} else {
					var all_located = fileRels.selectNodes('Item[@type=\'Located\']');
					// If file has more than one 'Located' then remove all of them except the
					// one that points to the default vault of the current user.
					// NOTE: it's a FUNDAMENTAL Innovator's approach - file is always
					//       submitted to the default vault of the current user. If this
					//       concept will be changed in the future then this code must be modified.
					var lcount = all_located.length;
					for (var j = 0; j < lcount; j++) {
						var located = all_located[j];
						var rNd = located.selectSingleNode('related_id');
						if (!rNd) {
							fileRels.removeChild(located);
						} else {
							var rvId = '';
							var rItemNd = rNd.selectSingleNode('Item[@type=\'Vault\']');
							if (rItemNd) {
								rvId = rItemNd.getAttribute('id');
							} else {
								rvId = rNd.text;
							}

							if (rvId != vaultServerID) {
								fileRels.removeChild(located);
							}
						}
					}
				}

				var fileLocated = fileRels.selectSingleNode('Item[@type=\'Located\']');
				if (!fileLocated) {
					fileLocated = this.createXmlElement('Item', fileRels);
					fileLocated.setAttribute('type', 'Located');
				}
				if (!fileLocated.getAttribute('action')) {
					var newLocatedAction = '';
					if (fileNd.getAttribute('action') == 'add') {
						newLocatedAction = 'add';
					} else {
						newLocatedAction = 'merge';
					}
					fileLocated.setAttribute('action', newLocatedAction);
				}

				// When file could have only one 'Located' we used on Located the condition 'where="1=1"' which essentially meant
				// "add if none or replace any existing Located on the File". With ability of a file to reside in multiple
				// vaults (i.e. item of type 'File' might have several 'Located' relationships) the behavior is "add Located
				// if file is not there yet; update the Located if the file already in the vault". This is achieved by
				// specifying on 'Located' condition 'where="related_id='{vault id}'"'. Note that additional condition
				// 'source_id={file id}' will be added on server when the sub-AML <Item type='Located' ...> is processed.
				if (!fileLocated.getAttribute('id') && !fileLocated.getAttribute('where')) {
					fileLocated.setAttribute('where', 'related_id=\'' + vaultServerID + '\'' /*"AND source_id='"+fileID+"'"*/);
				}
				this.setItemProperty(fileLocated, 'related_id', vaultServerID);
			}

			//code related to export/import functionality. server_id == donor_id.
			var server_id = this.getItemProperty(fileNd, 'server_id');
			if (server_id === '') {
				//this File is not exported thus check physical file.
				var checkedout_path = this.getItemProperty(fileNd, 'checkedout_path');
				var filename = this.getItemProperty(fileNd, 'filename');
				var FilePath;

				var itemId = this.getItemProperty(fileNd, 'id');
				var isFileSelected = false;
				if (this.getItemProperty(fileNd, 'file_size')) {
					isFileSelected = true;
				}

				if (!isFileSelected || !filename) {
					FilePath = vaultApplet.selectFile();
					if (!FilePath) {
						return null;
					}

					var parts = FilePath.split(/[\\\/]/);
					filename = parts[parts.length - 1];
					this.setItemProperty(fileNd, 'filename', filename);
				} else {
					if (checkedout_path) {
						if (0 === checkedout_path.indexOf('/')) {
							FilePath = checkedout_path + '/' + filename;
						} else {
							FilePath = checkedout_path + '\\' + filename;
						}
					} else {
						FilePath = aras.vault.vault.associatedFileList[itemId];
					}

				}

				this.setItemProperty(fileNd, 'checksum', vaultApplet.getFileChecksum(FilePath));
				this.setItemProperty(fileNd, 'file_size', vaultApplet.getFileSize(FilePath));

				vaultApplet.addFileToList(fileID, FilePath);
			}
		}

		var statusId = this.showStatusMessage('status', statusMsg, system_progressbar1_gif);
		var XMLdata = SoapConstants.EnvelopeBodyStart + '<ApplyItem>' +
						itemNd.xml + '</ApplyItem>' + SoapConstants.EnvelopeBodyEnd;

		vaultApplet.setClientData('XMLdata', XMLdata);

		return {
			vaultServerURL: vaultServerURL,
			vaultApplet: vaultApplet,
			statusId: statusId,
			win: win
		};
	}

	function _sendFilesWithVaultAppletAfter(params, XPath2ReturnedNd, boolRes) {
		if (!XPath2ReturnedNd) {
			XPath2ReturnedNd = this.XPathResult('/Item');
		}

		this.clearStatusMessage(params.statusId);

		var resXML = params.vaultApplet.getResponse();
		if (!boolRes || !resXML) {
			this.AlertError(this.getResource('', 'item_methods_ex.failed_upload_file', params.vaultServerURL), '', '', params.win);
			if (!boolRes) {
				resXML += params.vaultApplet.getLastError();
			}
			this.AlertError(this.getResource('', 'item_methods_ex.internal_error_occured'), boolRes + '\n' + resXML, this.getResource('', 'common.client_side_err'), params.win);
			return null;
		}

		var soapRes = new SOAPResults(this, resXML);

		var faultCode = soapRes.getFaultCode();
		if (faultCode !== 0 && faultCode !== '0') {//because user can has just add access and no get access
			this.AlertError(soapRes, params.win);
			return null;
		}

		var resDom = soapRes.results;
		if (this.hasMessage(resDom)) {// check for message
			this.refreshWindows(this.getMessageNode(resDom), resDom);
		}
		return resDom.selectSingleNode(XPath2ReturnedNd);
	}

	Aras.prototype.sendFilesWithVaultApplet = function Aras_sendFilesWithVaultApplet(itemNd, statusMsg, XPath2ReturnedNd) {
		/*----------------------------------------
		 * sendFilesWithVaultApplet
		 *
		 * Purpose:
		 * This function is for iternal use only. DO NOT use in User Methods
		 * Checks physical files.
		 * Sets headers and send physical files to Vault
		 *
		 * Arguments:
		 * itemNd    - xml node to be processed
		 * statusMsg - string to show in status bar while files being uploaded
		 * XPath2ReturnedNd = xpath to select returned node. Default: aras.XPathResult('/Item')
		 */
		var params = _sendFilesWithVaultAppletBefore.call(this, itemNd, statusMsg, XPath2ReturnedNd);
		if (!params) {
			return params;
		}
		var boolRes = params.vaultApplet.sendFiles(params.vaultServerURL);
		return _sendFilesWithVaultAppletAfter.call(this, params, XPath2ReturnedNd, boolRes);
	};

	Aras.prototype.sendFilesWithVaultAppletAsync = function Aras_sendFilesWithVaultAppletAsync(itemNd, statusMsg, XPath2ReturnedNd) {
		var params = _sendFilesWithVaultAppletBefore.call(this, itemNd, statusMsg, XPath2ReturnedNd);
		if (!params) {
			return Promise.resolve(params);
		}
		return params.vaultApplet.vault.sendFilesAsync(params.vaultServerURL).then(function(boolRes) {
			return _sendFilesWithVaultAppletAfter.call(this, params, XPath2ReturnedNd, boolRes);
		}.bind(this));
	};
})();

Aras.prototype.clientItemValidation = function Aras_clientItemValidation(itemTypeName, itemNd, breakOnFirstError, emptyPropertyWithDefaultValueCallback) {
	var resultErrors = [];
	var checkErrors = [];

	//general checks for the item to be saved: all required parameters should be set
	if (itemTypeName) {
		checkErrors = this.checkItemForErrors(itemNd, null, null, breakOnFirstError, emptyPropertyWithDefaultValueCallback);
		if (checkErrors.length > 0) {
			resultErrors = resultErrors.concat(checkErrors);
			if (breakOnFirstError) {
				return resultErrors;
			}
		}
	}

	//special checks for relationships and related items
	var newRelNodes = itemNd.selectNodes('Relationships/Item[@isDirty=\'1\' or @isTemp=\'1\']');
	var iter;
	for (iter = 0; iter < newRelNodes.length; iter++) {
		checkErrors = this.checkItemForErrors(newRelNodes[iter], 'source_id', null, breakOnFirstError, emptyPropertyWithDefaultValueCallback);
		if (checkErrors.length > 0) {
			resultErrors = resultErrors.concat(checkErrors);
			if (breakOnFirstError) {
				return resultErrors;
			}
		}
	}

	var newRelatedNodes = itemNd.selectNodes('Relationships/Item/related_id/Item[@isDirty=\'1\' or @isTemp=\'1\']');
	for (iter = 0; iter < newRelatedNodes.length; iter++) {
		checkErrors = this.checkItemForErrors(newRelatedNodes[iter], 'source_id', null, breakOnFirstError, emptyPropertyWithDefaultValueCallback);
		if (checkErrors.length > 0) {
			resultErrors = resultErrors.concat(checkErrors);
			if (breakOnFirstError) {
				return resultErrors;
			}
		}
	}

	return resultErrors;
};

(function() {
	function _saveItemExBefore(itemNd, confirmSuccess, doVersion) {
		if (!itemNd) {
			return null;
		}
		if (confirmSuccess === undefined || confirmSuccess === null) {
			confirmSuccess = true;
		}
		if (doVersion === undefined || doVersion === null) {
			doVersion = false;
		}

		var itemTypeName = itemNd.getAttribute('type');

		var win = this.uiFindWindowEx2(itemNd);

		//special checks for the item of ItemType type
		if (itemTypeName == 'ItemType' && !this.checkItemType(itemNd, win)) {
			return null;
		}

		var self = this;
		var defaultFieldCheckCallback = function (itemNode, reqName, proplabel, defVal) {
			var ask = self.confirm(self.getResource('', 'item_methods_ex.field_required_default_will_be_used', proplabel, defVal));
			if (ask) {
				self.setItemProperty(itemNode, reqName, defVal);
			}
			return {result: ask, message: ''};
		};

		var validationErrors = this.clientItemValidation(itemTypeName, itemNd, true, defaultFieldCheckCallback);
		if (validationErrors.length > 0) {
			if (validationErrors[0].message) {
				this.AlertError(validationErrors[0].message);
			}
			return null;
		}

		var backupCopy = itemNd;
		var oldParent = backupCopy.parentNode;
		itemNd = itemNd.cloneNode(true);
		this.prepareItem4Save(itemNd);

		var isTemp = this.isTempEx(itemNd);

		if (isTemp) {
			itemNd.setAttribute('action', 'add');
			this.setItemProperty(itemNd, 'locked_by_id', this.getCurrentUserID());

			if (itemTypeName == 'RelationshipType') {
				if (!itemNd.selectSingleNode('relationship_id/Item')) {
					var rsItemNode = itemNd.selectSingleNode('relationship_id');
					if (rsItemNode) {
						var rs = this.getItemById('', rsItemNode.text, 0);
						if (rs) {
							rsItemNode.text = '';
							rsItemNode.appendChild(rs.cloneNode(true));
						}
					}
				}

				var tmp001 = itemNd.selectSingleNode('relationship_id/Item');
				if (tmp001 && this.getItemProperty(tmp001, 'name') === '') {
					this.setItemProperty(tmp001, 'name', this.getItemProperty(itemNd, 'name'));
				}
			}
		} else if (doVersion) {
			itemNd.setAttribute('action', 'version');
		} else {
			itemNd.setAttribute('action', 'update');
		}

		var tempArray = [];
		this.doCacheUpdate(true, itemNd, tempArray);

		var statusMsg = '';
		if (isTemp) {
			statusMsg = this.getResource('', 'item_methods_ex.adding', itemTypeName);
		} else if (doVersion) {
			statusMsg = this.getResource('', 'item_methods_ex.versioning', itemTypeName);
		} else {
			statusMsg = this.getResource('', 'item_methods_ex.updating', itemTypeName);
		}

		return {
			confirmSuccess: confirmSuccess,
			itemTypeName: itemTypeName,
			backupCopy: backupCopy,
			statusMsg: statusMsg,
			oldParent: oldParent,
			tempArray: tempArray,
			itemNd: itemNd,
			win: win
		};
	}

	function _saveItemAfter(res, params) {
		if (!res) {
			return null;
		}

		var itemTypeName = params.itemTypeName;
		var win = params.win;
		var oldParent = params.oldParent;
		var backupCopy = params.backupCopy;
		var tempArray = params.tempArray;
		var confirmSuccess = params.confirmSuccess;
		var itemNd = params.itemNd;
		var itemID = itemNd.getAttribute('id');

		res.setAttribute('levels', '0');
		res.setAttribute('isEditState', this.isEditStateEx(backupCopy) ? '1' : '0');

		var newID = res.getAttribute('id');
		this.updateInCacheEx(backupCopy, res);
		var topWindow;

		if (win && win.isTearOff) {
			if (win.updateItemsGrid) {
				win.updateItemsGrid(res);
			}

			topWindow = window.opener ? this.getMostTopWindowWithAras(window.opener) : null;
			if (topWindow && topWindow.main) {
				if (itemTypeName === 'ItemType') {
					topWindow.updateTree(itemID.split(';'));
				} else if (itemTypeName === 'SelfServiceReport' && topWindow.main.work.itemTypeName === 'MyReports') {
					topWindow.main.work.updateReports();
				}
			}
		} else {
			topWindow = this.getMostTopWindowWithAras(window);
			if (itemTypeName == 'ItemType') {
				topWindow.updateTree(itemID.split(';'));
			}
		}

		if (itemTypeName == 'RelationshipType') {
			var relationship_id = this.getItemProperty(itemNd, 'relationship_id');
			if (relationship_id) {
				this.removeFromCache(relationship_id);
			}

		} else if (itemTypeName == 'ItemType') {
			var oldItemTypeName = !this.isTempEx(itemNd) ? this.getItemTypeName(itemID) : null;
			var item_name = (oldItemTypeName) ? oldItemTypeName : this.getItemProperty(itemNd, 'name');
			this.deletePropertyFromObject(this.sGridsSetups, item_name);
		}

		if (oldParent) {
			var tmpRes = oldParent.selectSingleNode('Item[@id="' + newID + '"]');
			if (tmpRes === null && newID != itemID && oldParent.selectSingleNode('Item[@id="' + itemID + '"]') !== null) {
				//possible when related item is versionable and relationship behavior is fixed
				//when relationship still points to previous generation.
				tmpRes = this.getFromCache(newID);
				this.updateInCacheEx(tmpRes, res);
				res = this.getFromCache(newID);
			} else {
				res = tmpRes;
			}
		} else {
			res = this.getFromCache(newID);
		}

		if (!res) {
			return null;
		}

		this.doCacheUpdate(false, itemNd, tempArray);

		ClearDependenciesInMetadataCache(this, itemNd);
		if (confirmSuccess) {
			var keyed_name = this.getKeyedNameEx(res);
			if (keyed_name && '' !== keyed_name) {
				this.AlertSuccess(this.getResource('', 'item_methods_ex.item_saved_successfully', '\'' + keyed_name + '\' '), win);
			} else {
				this.AlertSuccess(this.getResource('', 'item_methods_ex.item_saved_successfully', ''), win);
			}
		}
		params = this.newObject();
		params.itemID = itemID;
		params.itemNd = res;
		this.fireEvent('ItemSave', params);

		return res;
	}

	function getItemsGridContainer(itemTypeId) {
		const topWin = aras.getMainWindow();
		return topWin.arasTabs.getSearchGridTabs(itemTypeId || window.itemType.getAttribute('id'));
	}

	/*-- saveItemEx
	 *
	 *   Method to save an item
	 *   id = the id for the item to be saved
	 *
	 */
	Aras.prototype.saveItemEx = function Aras_saveItemEx(itemNd, confirmSuccess, doVersion) {
		var params = _saveItemExBefore.call(this, itemNd, confirmSuccess, doVersion);
		if (!params) {
			return params;
		}
		var res = this.applyItemWithFilesCheck(params.itemNd, params.win, params.statusMsg, this.XPathResult('/Item'));
		return _saveItemAfter.call(this, res, params);
	};

	Aras.prototype.saveItemExAsync = function Aras_saveItemExAsync(itemNd, confirmSuccess, doVersion, isGridUpdate) {
		var params = _saveItemExBefore.call(this, itemNd, confirmSuccess, doVersion);
		if (!params) {
			return Promise.resolve(params);
		}
		return this.applyItemWithFilesCheckAsync(params.itemNd, params.win, params.statusMsg, this.XPathResult('/Item'), isGridUpdate).then(function (res) {
			return _saveItemAfter.call(this, res, params);
		}.bind(this));
	};

	Aras.prototype.decorateForMultipleGrids = function Aras_decorateForMultipleGrids(fn) {
		const decoratedFunction = function(itemNode) {
			const initialArguments = Array.from(arguments);
			const itemTypeId = (itemNode && typeof itemNode !== 'string') ? itemNode.getAttribute('typeId') : '';
			const itemsGrids = getItemsGridContainer(itemTypeId);

			itemsGrids.forEach(function(itemsGrid) {
				const extendedArguments = initialArguments.slice(0);
				extendedArguments.unshift(itemsGrid);
				fn.apply(null, extendedArguments);
			});
		};
		return decoratedFunction;
	};
})();

Aras.prototype.doCacheUpdate = function Aras_doCacheUpdate(prepare, itemNd, tempArray) {
	var nodes;
	var i;
	if (prepare) {
		nodes = itemNd.selectNodes('descendant-or-self::Item[@id and (@action="add" or @action="create")]');
		for (i = 0; i < nodes.length; i++) {
			tempArray.push(new Array(nodes[i].getAttribute('id'), nodes[i].getAttribute('type')));
		}

	} else {
		for (i = 0; i < tempArray.length; i++) {
			nodes = this.itemsCache.getItemsByXPath('/Innovator/Items//Item[@id="' + tempArray[i][0] + '" and (@action="add" or @action="create")]');
			for (var o = 0; o < nodes.length; o++) {
				nodes[o].setAttribute('action', 'skip');
				nodes[o].removeAttribute('isTemp');
				nodes[o].removeAttribute('isDirty');
			}
			if (i === 0) {
				continue;
			}
			var itemID = tempArray[i][0];
		}
	}
};

Aras.prototype.downloadFile = function ArasDownloadFile(fileNd, preferredName) {
	var fileURL = this.getFileURLEx(fileNd);
	if (!fileURL) {
		this.AlertError(this.getResource('', 'item_methods_ex.failed_download_file_url_empty'));
		return false;
	}

	if (preferredName) {
		this.vault.setLocalFileName(preferredName);
	}
	var isSucceeded = this.vault.downloadFile(fileURL);
	if (!isSucceeded) {
		this.AlertError(this.getResource('', 'item_methods_ex.failed_download_file'));
		return false;
	}
	return true;
};

// === lockItemEx ====
// Method to lock the item passing the item object
// itemNode = the item
// ===================
Aras.prototype.lockItemEx = function Aras_lockItemEx(itemNode) {
	var ownerWindow = this.uiFindWindowEx2(itemNode),
		itemID = itemNode.getAttribute('id'),
		itemTypeName = itemNode.getAttribute('type'),
		itemType = this.getItemTypeDictionary(itemTypeName),
		isRelationship = this.getItemProperty(itemType.node, 'is_relationship'),
		isPolyItem = this.isPolymorphic(itemType.node);

	if (isRelationship == '1' && this.isDirtyEx(itemNode)) {
		var sourceNd = itemNode.selectSingleNode('../..');

		if (sourceNd && this.isDirtyEx(sourceNd)) {
			var itLabel = this.getItemProperty(itemType.node, 'label') || this.getItemProperty(itemType.node, 'name'),
				param = {
					aras: this,
					buttons: {btnOK: this.getResource('', 'common.ok'), btnCancel: this.getResource('', 'common.cancel')},
					defaultButton: 'btnCancel',
					message: this.getResource('', 'item_methods_ex.locking_it_lose_changes', itLabel)
				},
				options = {dialogWidth: 300, dialogHeight: 150, center: true},
				result;
			if (window.showModalDialog) {
				result = this.modalDialogHelper.show('DefaultModal', ownerWindow, param, options, 'groupChgsDialog.html');
			} else {
				result = window.confirm(param.message) ? 'btnYes' : 'btnCancel';
			}

			if (result == 'btnCancel') {
				return null;
			}
		}
	}

	var statusId = this.showStatusMessage('status', this.getResource('', 'common.locking_item_type', itemTypeName), system_progressbar1_gif),
		bodyStr = '<Item type=\'' + (!isPolyItem ? itemTypeName : this.getItemTypeName(this.getItemProperty(itemNode, 'itemtype'))) + '\' id=\'' + itemID + '\' action=\'lock\' />',
		requestResult = this.soapSend('ApplyItem', bodyStr),
		returnedItem;

	this.clearStatusMessage(statusId);

	var faultCode = requestResult.getFaultCode();
	if (faultCode !== 0 && faultCode !== '0') {
		this.AlertError(requestResult, ownerWindow);
		return null;
	}

	returnedItem = requestResult.results.selectSingleNode(this.XPathResult('/Item'));
	if (returnedItem) {
		var oldParent = itemNode.parentNode;

		returnedItem.setAttribute('loadedPartialy', '0');
		this.updateInCacheEx(itemNode, returnedItem);

		if (oldParent) {
			itemNode = oldParent.selectSingleNode('Item[@id="' + itemID + '"]') || oldParent.selectSingleNode('Item');
		} else {
			itemNode = this.getFromCache(itemID);
		}

		this.fireEvent('ItemLock', {itemID: itemNode.getAttribute('id'), itemNd: itemNode, newLockedValue: this.isLocked(itemNode)});
		return itemNode;
	} else {
		this.AlertError(this.getResource('', 'item_methods_ex.failed_get_item_type_from_sever', itemTypeName), '', '', ownerWindow);
		return null;
	}
};

// === unlockItemEx ====
// Method to unlock the item passing the item object
// itemNode = the item
// =====================
Aras.prototype.unlockItemEx = function Aras_unlockItemEx(itemNode, saveChanges) {
	var itemTypeName = itemNode.getAttribute('type'),
		ownerWindow = this.uiFindWindowEx2(itemNode);

	if (this.isTempEx(itemNode)) {
		this.AlertError(this.getResource('', 'item_methods_ex.failed_unlock_item_type', itemTypeName), '', '', ownerWindow);
		return null;
	}

	var itemType = this.getItemTypeDictionary(itemTypeName),
		isPolyItem = (itemType && itemType.node) ? this.isPolymorphic(itemType.node) : false;

	if (saveChanges === undefined) {
		var isDirty = this.isDirtyEx(itemNode);

		if (isDirty) {
			var options = {dialogWidth: 400, dialogHeight: 200, center: true},
				params = {
					aras: this,
					message: this.getResource('', 'item_methods_ex.unlocking_discard_your_changes', itemTypeName, this.getKeyedNameEx(itemNode)),
					buttons: {
						btnYes: this.getResource('', 'common.yes'),
						btnSaveAndUnlock: this.getResource('', 'item_methods_ex.save_first'),
						btnCancel: this.getResource('', 'common.cancel')
					},
					defaultButton: 'btnCancel'
				},
				returnedValue;

			if (window.showModalDialog) {
				returnedValue = this.modalDialogHelper.show('DefaultModal', ownerWindow, params, options, 'groupChgsDialog.html');
			} else {
				returnedValue = 'btnCancel';
				if (window.confirm(this.getResource('', 'item_methods_ex.save_your_changes', itemTypeName, this.getKeyedNameEx(itemNode)))) {
					returnedValue = 'btnSaveAndUnlock';
				} else if (window.confirm(this.getResource('', 'item_methods_ex.unlocking_discard_your_changes', itemTypeName, this.getKeyedNameEx(itemNode)))) {
					returnedValue = 'btnYes';
				}
			}

			if (returnedValue == 'btnCancel') {
				return null;
			} else {
				saveChanges = (returnedValue != 'btnYes');
			}
		}
	}

	if (saveChanges) {
		itemNode = this.saveItemEx(itemNode);

		if (!itemNode) {
			return null;
		}
		if (itemTypeName === 'Preference') {
			const mainWindow = aras.getMainWindow();
			mainWindow.mainLayout.observer.notify('UpdatePreferences');
		}
	}

	var statusId = this.showStatusMessage('status', this.getResource('', 'item_methods_ex.unlocking_itemtype', itemTypeName), system_progressbar1_gif),
		itemId = itemNode.getAttribute('id'),
		lockedById = itemNode.selectSingleNode('locked_by_id'),
		queryResult;

	if (!lockedById) {
		queryResult = this.soapSend('ApplyItem', '<Item type=\'' + itemTypeName + '\' id=\'' + itemId + '\' action=\'get\' />');
	} else {
		queryResult = this.soapSend('ApplyItem', '<Item type=\'' + (!isPolyItem ? itemTypeName : this.getItemTypeName(this.getItemProperty(itemNode, 'itemtype'))) + '\' id=\'' + itemId + '\' action=\'unlock\' />', '', saveChanges);
	}
	this.clearStatusMessage(statusId);

	if (!queryResult.getFaultCode()) {
		var resultItem = queryResult.results.selectSingleNode(this.XPathResult('/Item')),
			newResult;

		if (resultItem) {
			resultItem.setAttribute('loadedPartialy', '0');

			var oldParent = itemNode.parentNode;
			this.updateInCacheEx(itemNode, resultItem);
			this.updateFilesInCache(resultItem);

			newResult = oldParent ? oldParent.selectSingleNode('Item[@id="' + itemId + '"]') : this.getFromCache(itemId);
			resultItem = newResult || resultItem;

			this.fireEvent('ItemLock', {itemID: resultItem.getAttribute('id'), itemNd: resultItem, newLockedValue: this.isLocked(resultItem)});
			return resultItem;
		} else {
			this.AlertError(this.getResource('', 'item_methods_ex.failed_get_item_type_from_server', itemTypeName), '', '', ownerWindow);
			return null;
		}
	} else {
		this.AlertError(queryResult, ownerWindow);
		return null;
	}
};

Aras.prototype.updateFilesInCache = function Aras_updateFilesInCache(itemNd) {
	var itemTypeName = itemNd.getAttribute('type'),
		isDiscoverOnly = itemNd.getAttribute('discover_only') == '1';

	if (itemTypeName != 'File' && !isDiscoverOnly) {
		var itemType = this.getItemTypeForClient(itemTypeName).node,
			fileProperties = this.getPropertiesOfTypeFile(itemType),
			propertyName, fileId, fileNode,
			queryItem, queryResult, i;

		for (i = 0; i < fileProperties.length; i++) {
			propertyName = this.getItemProperty(fileProperties[i], 'name');
			fileId = this.getItemProperty(itemNd, propertyName);

			if (fileId) {
				this.removeFromCache(fileId);

				queryItem = new this.getMostTopWindowWithAras(window).Item();
				queryItem.setType('File');
				queryItem.setAction('get');
				queryItem.setID(fileId);
				queryItem.setAttribute('select', 'filename,file_size,file_type,checkedout_path,comments,checksum,label,mimetype');
				queryResult = queryItem.apply();

				if (queryResult.isEmpty()) {
					continue;
				} else {
					if (!queryResult.isError()) {
						fileNode = queryResult.getItemByIndex(0).node;
						this.updateInCache(fileNode);
					} else {
						this.AlertError(queryResult);
						return;
					}
				}
			}
		}
	}
};

Aras.prototype.purgeItemEx = function Aras_purgeItemEx(itemNd, silentMode) {
	/*-- purgeItem
	*
	*   Method to delete the latest version of the item (or the item if it's not versionable)
	*   itemNd -
	*   silentMode - flag to know if user confirmation is NOT needed
	*
	*/
	return this.PurgeAndDeleteItem_CommonPartEx(itemNd, silentMode, 'purge');
};

Aras.prototype.deleteItemEx = function Aras_deleteItemEx(itemNd, silentMode) {
	/*-- deleteItem
	*
	*   Method to delete all versions of the item
	*   itemNd -
	*   silentMode - flag to know if user confirmation is NOT needed
	*
	*/
	return this.PurgeAndDeleteItem_CommonPartEx(itemNd, silentMode, 'delete');
};

Aras.prototype.PurgeAndDeleteItem_CommonPartEx = function Aras_PurgeAndDeleteItem_CommonPartEx(itemNd, silentMode, purgeORdelete) {
	/*-- PurgeAndDeleteItem_CommonPartEx
	*
	*   This method is for ***internal purposes only***.
	*
	*/

	if (silentMode === undefined) {
		silentMode = false;
	}

	var ItemId = itemNd.getAttribute('id');
	var ItemTypeName = itemNd.getAttribute('type');

	//prepare
	if (!silentMode && !this.Confirm_PurgeAndDeleteItem(ItemId, this.getKeyedNameEx(itemNd), purgeORdelete)) {
		return false;
	}

	var DeletedItemTypeName;
	var relationship_id;
	if (!this.isTempEx(itemNd)) {
		//save some information
		if (ItemTypeName == 'ItemType') {
			if (this.getItemProperty(itemNd, 'is_relationship') == '1') {
				relationship_id = ItemId;
			}
			DeletedItemTypeName = this.getItemProperty(itemNd, 'name');

		} else if (ItemTypeName == 'RelationshipType') {
			relationship_id = this.getItemProperty(itemNd, 'relationship_id');
			DeletedItemTypeName = this.getItemProperty(itemNd, 'name');
		}

		//delete
		if (!this.SendSoap_PurgeAndDeleteItem(ItemTypeName, ItemId, purgeORdelete)) {
			return false;
		}
	}

	itemNd.setAttribute('action', 'skip');

	//remove node from parent
	var tmpNd = itemNd.parentNode;
	if (tmpNd) {
		tmpNd.removeChild(itemNd);
	}

	//delete all dependent stuff
	this.RemoveGarbage_PurgeAndDeleteItem(ItemTypeName, ItemId, DeletedItemTypeName, relationship_id);
	this.MetadataCache.RemoveItemById(ItemId);

	return true;
};

Aras.prototype.getKeyedNameEx = function Aras_getKeyedNameEx(itemNd) {
	/*----------------------------------------
	* getKeyedNameEx
	*
	* Purpose: build and return keyed name of an Item.
	*
	* Arguments:
	* itemNd - xml node of Item to get keyed name of.
	*/

	var res = '';
	if (itemNd.nodeName != 'Item') {
		return res;
	}

	if ((!this.isDirtyEx(itemNd)) && (!this.isTempEx(itemNd))) {
		res = itemNd.getAttribute('keyed_name');
		if (res) {
			return res;
		}
		res = this.getItemProperty(itemNd, 'keyed_name');
		if (res !== '') {
			return res;
		}
	}

	const itemTypeName = itemNd.getAttribute('type');
	const itemType = this.getItemTypeDictionary(itemTypeName);
	if (!itemType) {
		return res;
	}

	const itemTypeLabel = itemType.getProperty('label', '');
	const itemID = itemNd.getAttribute('id');

	if (this.isTempEx(itemNd)) {
		let itemTypeTabs = this.tabsTitles[itemTypeName];
		if (!itemTypeTabs) {
			itemTypeTabs = this.newObject();
		}

		if (!itemTypeTabs[itemID]) {
			const tabId = Object.keys(itemTypeTabs).length + 1;
			const tabTitle = (itemTypeLabel || itemTypeName) + ' ' + tabId;
			itemTypeTabs[itemID] = tabTitle;
			this.tabsTitles[itemTypeName] = itemTypeTabs;
		}

		res = itemTypeTabs[itemID];
	} else {
		res = itemID;
	}

	var relationshipItems = itemType.node.selectNodes('Relationships/Item[@type="Property"]');
	var tmpArr = []; //pairs keyOrder -> propValue
	var counter = 0;
	var i;
	for (i = 0; i < relationshipItems.length; i++) {
		var propNd = relationshipItems[i];
		var propName = this.getItemProperty(propNd, 'name');
		if (propName === '') {
			continue;
		}

		var keyOrder = this.getItemProperty(propNd, 'keyed_name_order');
		if (keyOrder === '') {
			continue;
		}

		var node = itemNd.selectSingleNode(propName);
		if (!node || node.childNodes.length != 1) {
			continue;
		}

		var txt = '';
		if (node.firstChild.nodeType == 1) {//if nested Item
			txt = this.getKeyedNameEx(node.firstChild);
		} else {
			txt = node.text;
		}

		if (txt !== '') {
			tmpArr[counter] = new Array(keyOrder, txt);
			counter++;
		}
	}

	if (tmpArr.length > 0) {
		tmpArr = tmpArr.sort(keyedNameSorter);
		res = tmpArr[0][1];
		for (i = 1; i < tmpArr.length; i++) {
			res += ' ' + tmpArr[i][1];
		}
	}

	return res;
};

Aras.prototype.getKeyedNameAttribute = function(node, element) {
	if (!node) {
		return;
	}
	var value;
	var tmpNd = node.selectSingleNode(element);
	if (tmpNd) {
		value = tmpNd.getAttribute('keyed_name');
		if (!value) {
			value = '';
		}
	} else {
		value = '';
	}
	return value;
};

function keyedNameSorter(a, b) {
	var s1 = parseInt(a[0]);
	if (isNaN(s1)) {
		return 1;
	}
	var s2 = parseInt(b[0]);
	if (isNaN(s2)) {
		return -1;
	}

	if (s1 < s2) {
		return -1;
	} else if (s1 == s2) {
		return 0;
	} else {
		return 1;
	}
}

/*-- getItemRelationshipsEx
*
*   Method to
*
*
*/
Aras.prototype.getItemRelationshipsEx = function(itemNd, relsName, pageSize, page, body, forceReplaceByItemFromServer) {
	if (!(itemNd && relsName)) {
		return null;
	}
	if (pageSize === undefined || pageSize === null) {
		pageSize = '';
	}
	if (page === undefined || page === null) {
		page = '';
	}
	if (body === undefined || body === null) {
		body = '';
	}
	if (forceReplaceByItemFromServer === undefined || forceReplaceByItemFromServer === null) {
		forceReplaceByItemFromServer = false;
	}

	var itemID = itemNd.getAttribute('id');
	var itemTypeName = itemNd.getAttribute('type');
	var res = null;

	if (!forceReplaceByItemFromServer && (pageSize == -1 || this.isTempID(itemID) || (itemNd.getAttribute('levels') && parseInt(itemNd.getAttribute('levels')) > 0))) {
		if (!isNaN(parseInt(pageSize)) && parseInt(pageSize) > 0 && !isNaN(parseInt(page)) && parseInt(page) > -1) {
			res = itemNd.selectNodes('Relationships/Item[@type="' + relsName + '" and @page="' + page + '"]');
			if (res && res.length == pageSize) {
				return res;
			}
		} else {
			res = itemNd.selectNodes('Relationships/Item[@type="' + relsName + '"]');
			if (res && res.length > 0) {
				return res;
			}
		}
	}

	var bodyStr = '<Item type="' + itemTypeName + '" id="' + itemID + '" relName="' + relsName + '" action="getItemRelationships"';
	if (pageSize) {
		bodyStr += ' pageSize="' + pageSize + '"';
	}
	if (page) {
		bodyStr += ' page="' + page + '"';
	}
	if (body === '') {
		bodyStr += '/>';
	} else {
		bodyStr += '>' + body + '</Item>';
	}

	res = this.soapSend('ApplyItem', bodyStr);

	var faultCode = res.getFaultCode();
	if (faultCode !== 0 && faultCode !== '0') {
		this.AlertError(res);
		return null;
	}

	if (!itemNd.selectSingleNode('Relationships')) {
		this.createXmlElement('Relationships', itemNd);
	}

	var rels = res.results.selectNodes(this.XPathResult('/Item[@type="' + relsName + '"]'));
	var itemRels = itemNd.selectSingleNode('Relationships');
	var idsStr = '';
	for (var i = 0; i < rels.length; i++) {
		var rel = rels[i].cloneNode(true);
		var relId = rel.getAttribute('id');
		if (i > 0) {
			idsStr += ' or ';
		}
		idsStr += '@id="' + relId + '"';
		var prevRel = itemRels.selectSingleNode('Item[@type="' + relsName + '" and @id="' + relId + '"]');
		if (prevRel) {
			if (forceReplaceByItemFromServer) {
				// By some reason the previous implementation did not replaced existing on the node
				// relationships with the new relationships obtained from the server but rather
				// just removed some attributes on them (like "pagesize", etc.). From other side those
				// relationships that don't exist on the 'itemNd' are added to it. This is wrong as
				// the newly obtained relationships even if they already exist on 'itemNd' might have
				// some properties that are different in db from what is in the client memory.
				// NOTE: the fix will break the case when the client changes some relationship properties
				//       in memory and then calls this method expecting that these properties will stay unchanged,
				//       but: a) this method seems to be called only from getFileURLEx(..); b) if the above
				//       behavior is expected then another method is probably required which must be called
				//       something like 'mergeRelationships'.
				// by Andrey Knourenko
				itemRels.removeChild(prevRel);
			} else {
				this.mergeItem(prevRel, rel);
				continue;
			}
		}
		itemRels.appendChild(rel);
	}
	itemNd.setAttribute('levels', '0');
	if (idsStr === '') {
		return null;
	}
	res = itemRels.selectNodes('Item[@type="' + relsName + '" and (' + idsStr + ')]');

	return res;
};

/*-- getItemLastVersionEx
*
*   Method to load the latest version for the item
*   itemTypeName = the ItemType name
*   itemId       = the id for the item
*
*/
Aras.prototype.getItemLastVersionEx = function(itemNd) {
	var res = this.soapSend('ApplyItem', '<Item type="' + itemNd.getAttribute('type') + '" id="' + itemNd.getAttribute('id') + '" action="getItemLastVersion" />');

	var faultCode = res.getFaultCode();
	if (faultCode !== 0 && faultCode !== '0') {
		return null;
	}

	res = res.results.selectSingleNode(this.XPathResult('/Item'));
	if (!res) {
		return null;
	}

	itemNd.parentNode.replaceChild(res, itemNd);

	return res;
}; //getItemLastVersionEx

Aras.prototype.downloadItemFiles = function Aras_downloadItemFiles(itemNd) {
	/*
	this method is for internal use *** only ***
	*/
	if (!itemNd) {
		return false;
	}

	var itemTypeName = itemNd.getAttribute('type');
	var itemType = this.getItemTypeForClient(itemTypeName).node;
	var fileProps = this.getPropertiesOfTypeFile(itemType);

	for (var i = 0; i < fileProps.length; i++) {
		var propNm = this.getItemProperty(fileProps[i], 'name');
		var fileNd = itemNd.selectSingleNode(propNm + '/Item');
		if (!fileNd) {
			var fileID = this.getItemProperty(itemNd, propNm);
			if (!fileID) {
				continue;
			}

			fileNd = this.getItemFromServer('File', fileID, 'filename').node;
		}

		if (!fileNd) {
			continue;
		}

		this.downloadFile(fileNd);
	}

	return true;
};

Aras.prototype.promoteEx = function Aras_promoteEx(itemNd, stateName, comments, soapController) {
	if (!itemNd) {
		return null;
	}

	var itemID = itemNd.getAttribute('id');
	var itemTypeName = itemNd.getAttribute('type');

	var promoteParams = {
		typeName: itemTypeName,
		id: itemID,
		stateName: stateName,
		comments: comments
	};

	var res = this.promoteItem_implementation(promoteParams, soapController);
	if (!res) {
		return null;
	}

	var oldParent = itemNd.parentNode;
	this.updateInCacheEx(itemNd, res);

	if (oldParent) {
		res = oldParent.selectSingleNode('Item[@id="' + itemID + '"]');
	} else {
		res = this.getFromCache(itemID);
	}

	var params = this.newObject();
	params.itemID = res.getAttribute('id');
	params.itemNd = res;
	this.fireEvent('ItemSave', params);

	return res;
};

Aras.prototype.getFileURLEx = function Aras_getFileURLEx(itemNd) {
	/*
	* Private method that returns 'Located' pointing to the vault in which the
	* specified file resides. The vault is selected by the following algorithm:
	*   - if file is not stale in the default vault of the current user then return this vault
	*   - else return the first vault in which the file is not stale
	* NOTE: file is called 'not stale' in vault if 'Located' referencing the vault has
	*       the maximum value of property 'file_version' among other 'Located' of the same file.
	*/
	function getLocatedForFile(aras, itemNd) {
		var fitem = aras.newIOMItem();
		fitem.loadAML(itemNd.xml);
		var all_located = fitem.getRelationships('Located');

		// First find the max 'file_version' among all 'Located' rels
		var maxv = 0;
		var lcount = all_located.getItemCount();
		var i;
		var located;
		var file_version;
		for (i = 0; i < lcount; i++) {
			located = all_located.getItemByIndex(i);
			file_version = located.getProperty('file_version') * 1;
			if (file_version > maxv) {
				maxv = file_version;
			}
		}

		var sorted_located = getSortedLocatedList(aras, fitem, all_located);

		// Now go through the sorted list and return first non-stale vault
		for (i = 0; i < sorted_located.length; i++) {
			located = sorted_located[i];
			file_version = located.getProperty('file_version') * 1;
			if (file_version == maxv) {
				return located.node;
			}
		}

		// It should never reach this point as at least one of vaults has non-stale file.
		return null;
	}

	// Build a list of 'Located' sorted by the priorities of vaults that they reference.
	// Sorting is done based on the 'ReadPriority' relationships of the current user + the
	// default vault of the user + remaining vaults.
	function getSortedLocatedList(aras, fitem, all_located) {
		var lcount = all_located.getItemCount();

		var sorted_located = [];

		// Get all required information (default vault; etc.) for the current user
		var aml = '<Item type=\'User\' action=\'get\' select=\'default_vault\' expand=\'1\'>' +
				'  <id>' + aras.getUserID() + '</id>' +
				'  <Relationships>' +
				'    <Item type=\'ReadPriority\' action=\'get\' select=\'priority, related_id\' expand=\'1\' orderBy=\'priority\'/>' +
				'  </Relationships>' +
				'</Item>';

		var ureq = aras.newIOMItem();
		ureq.loadAML(aml);
		var uresult = ureq.apply();
		if (uresult.isError()) {
			throw new Error(1, uresult.getErrorString());
		}

		// Note that because the above AML has 'orderBy' the 'all_rps' collection is sorted
		// by ReadPriority.priority.
		var all_rps = uresult.getRelationships('ReadPriority');
		var rpcount = all_rps.getItemCount();
		var i;
		var l;
		var located;
		for (i = 0; i < rpcount; i++) {
			var vault = all_rps.getItemByIndex(i).getRelatedItem();
			// If the file is in the vault from the "ReadPriority" then add 'Located' that references
			// the vault to the sorted list.
			for (l = 0; l < lcount; l++) {
				located = all_located.getItemByIndex(l);
				if (vault.getID() == located.getRelatedItem().getID()) {
					sorted_located[sorted_located.length] = located;
					break;
				}
			}
		}

		// Now append the 'Located' to the default vault to the list if it's not there yet
		// (providing that the file is in the default vault).
		var dvfound = false;
		var default_vault = uresult.getPropertyItem('default_vault');
		for (i = 0; i < sorted_located.length; i++) {
			if (sorted_located[i].getRelatedItem().getID() == default_vault.getID()) {
				dvfound = true;
				break;
			}
		}
		if (!dvfound) {
			for (i = 0; i < lcount; i++) {
				located = all_located.getItemByIndex(i);
				if (default_vault.getID() == located.getRelatedItem().getID()) {
					sorted_located[sorted_located.length] = located;
					break;
				}
			}
		}

		// Finally append 'Located' to all remaining vaults that the file resides in but that are
		// not in the sorted list yet.
		for (i = 0; i < lcount; i++) {
			located = all_located.getItemByIndex(i);
			var vfound = false;
			for (l = 0; l < sorted_located.length; l++) {
				if (sorted_located[l].getID() == located.getID()) {
					vfound = true;
					break;
				}
			}
			if (!vfound) {
				sorted_located[sorted_located.length] = located;
			}
		}

		return sorted_located;
	}

	/*----------------------------------------
	* getFileURLEx
	*
	* Purpose:
	* get file URL using the following algorithm:
	*   - take the default vault of the current user unless the file does not exist or stale in the vault
	*   - otherwise take the first vault in which the file is not stale
	*
	* Arguments:
	* itemNd - xml node of the File to be downloaded
	*
	*/
	this.getItemRelationshipsEx(itemNd, 'Located', undefined, undefined, undefined, true);
	var locatedNd = getLocatedForFile(this, itemNd);

	if (!locatedNd) {
		this.AlertError(this.getResource('', 'item_methods_ex.failed_get_file_vault_could_not_be_located'));
		return '';
	}

	var vaultNode = locatedNd.selectSingleNode('related_id/Item[@type="Vault"]');
	var vault_id = '';
	if (!vaultNode) {
		vault_id = locatedNd.selectSingleNode('related_id').text;
		vaultNode = this.getItemById('Vault', vault_id, 0);
	} else {
		vault_id = vaultNode.getAttribute('id');
	}

	var vaultServerURL = vaultNode.selectSingleNode('vault_url').text;
	if (vaultServerURL === '') {
		return '';
	}

	vaultServerURL = this.TransformVaultServerURL(vaultServerURL);

	var fileID = itemNd.getAttribute('id');
	var fileName = this.getItemProperty(itemNd, 'filename');
	var fileURL = vaultServerURL +
		'?dbName=' + encodeURIComponent(this.getDatabase()) +
		'&fileID=' + encodeURIComponent(fileID) +
		'&fileName=' + encodeURIComponent(fileName) +
		'&vaultId=' + vault_id;
	return fileURL;
};

Aras.prototype.replacePolyItemNodeWithNativeItem = function Aras_replacePolyItemNodeWithNativeItem(ritem) {
	if (!(ritem && ritem.parentNode)) {
		this.AlertError('Item is null or doesn\'t have parent item.');
		return ritem;
	}
	var typeId = ritem.getAttribute('typeId');
	var relatedItemType = this.getItemTypeForClient(typeId, 'id').node;
	if (!relatedItemType) {
		this.AlertError('Can\'t get type of related item.');
		return ritem;
	}

	if (this.isPolymorphic(relatedItemType)) {
		var nativeRelatedITID = this.getItemProperty(ritem, 'itemtype');
		var relatedItemNd = this.getItemTypeForClient(nativeRelatedITID, 'id').node;
		if (!relatedItemNd) {
			this.AlertError('Can\'t get native item type of polymorphic item.');
			return ritem;
		}
		var nativeRelated = this.getItemFromServer(this.getItemProperty(relatedItemNd, 'name'), ritem.getAttribute('id'), '*').node;
		if (nativeRelated) {
			ritem.parentNode.replaceChild(nativeRelated, ritem);
			return nativeRelated;
		}
	}
	return ritem;
};

/** itemtype_methods.js **/
// © Copyright by Aras Corporation, 2004-2008.

/*
 *   The ItemType methods extension for the Aras Object.
 *
 */

/*-- getItemTypeProperties
 *
 *   Method to get the properties for the ItemType
 *   itemType = the itemType
 *
 */
Aras.prototype.getItemTypeProperties = function(itemType) {
	if (!itemType) {
		return;
	}
	with (this) {
		return itemType.selectNodes('Relationships/Item[@type="Property"]');
	}
};

Aras.prototype.rebuildView = function(viewId) {
	if (!viewId) {
		this.AlertError(this.getResource('', 'itemtype_methods.view_to_rebuild_not_specified'), '', '');
		return false;
	}

	with (this) {
		var statusId = showStatusMessage('status', this.getResource('', 'itemtype_methods.rebuilding_view'), '../images/Progress.gif');
		var res = soapSend('RebuildView', '<Item type="View" id="' + viewId + '" />');
		clearStatusMessage(statusId);
		if (res.getFaultCode() != 0) {
			this.AlertError(res);
			return false;
		}

		var formNd = res.results.selectSingleNode('//Item[@type="Form"]');
		if (!formNd) {
			return false;
		}

		var oldView = itemsCache.getItemByXPath('/Innovator/Items/Item[@type="ItemType"]/Relationships/Item[@type="View" and @id="' + viewId + '"]');
		itemsCache.addItem(formNd);

		var formId = formNd.getAttribute('id');
		var newView = getItem('View', 'related_id/Item/@id="' + formId + '"', '<related_id>' + formId + '</related_id>', 0);

		if (oldView) {
			oldView.parentNode.replaceChild(newView, oldView);
		}
		if (uiFindWindowEx(viewId)) {
			uiReShowItemEx(viewId, newView);
		}
	}
	return true;
};

Aras.prototype.isPolymorphic = function(itemType) {
	var implementationType = this.getItemProperty(itemType, 'implementation_type');
	return (implementationType == 'polymorphic');
};

Aras.prototype.getMorphaeList = function(itemType) {
	var morphae = itemType.selectNodes('Relationships/Item[@type=\'Morphae\']/related_id/Item');
	return _fillItemTypeList(morphae, this);

};

Aras.prototype.getPolymorphicsWhereUsedAsPolySource = function(itemTypeId) {
	var polyItems = this.applyItem(
		'<Item type=\'ItemType\' action=\'get\' select=\'id, name, label\'>' +
			'<Relationships>' +
				'<Item type=\'Morphae\' action=\'get\' select=\'id\'>' +
					'<related_id>' + itemTypeId + '</related_id>' +
				'</Item>' +
			'</Relationships>' +
		'</Item>');
	if (polyItems) {
		var tmpDoc = this.createXMLDocument();
		tmpDoc.loadXML(polyItems);
		polyItems = tmpDoc.selectNodes('Result/Item[@type=\'ItemType\']');
	} else {
		return [];
	}
	return _fillItemTypeList(polyItems, this);
};

function _fillItemTypeList(nodes, aras) {
	var result = [];
	for (var i = 0; i < nodes.length; i++) {
		var node = nodes[i];
		var id = node.getAttribute('id');
		var name = aras.getItemProperty(node, 'name');
		var label = aras.getItemProperty(node, 'label');
		if (label === null || label === '') {
			label = name;
		}
		result.push({id: id, name: name, label: label});
	}
	return result;
}

/** ui_methods.js **/
// (c) Copyright by Aras Corporation, 2004-2011.

///--- User Interface methods ---///
/*
* uiShowItem
*
* parameters:
* 1) itemTypeName - may be empty string if item is in client cache
* 2) itemID       - obligatory
* 3) viewMode     - 'tab view' or 'openFile'
*                    if not specified aras.getVariable('viewMode') is used
* 4) isTearOff    - true or false, if not specified aras.getVariable('TearOff') is used
*/
Aras.prototype.uiShowItem = function (itemTypeName, itemID, viewMode, isUnfocused) {

	if (!itemID) return false;
	viewMode = viewMode || "tab view";
	var itemNd = this.getItemById(itemTypeName, itemID, 0, undefined, "*");

	if (!itemNd) {
		this.AlertError(this.getResource('','ui_methods.access_restricted_or_not_exist', itemTypeName));
		return false;
	}
	return this.uiShowItemEx(itemNd, viewMode, null, isUnfocused);
};


/*
* uiReShowItem
*
* parameters:
* 1) oldItemId- old id of item to be shown
* 2) itemId   - id of item to be shown //usually itemId==oldItemId
* 2) editMode - 'view' or 'edit'
* 3) viewMode - 'tab view', ' or 'openFile'
* 4) isTearOff- true or false.
*/
Aras.prototype.uiReShowItem = function (oldItemId, itemId, editMode, viewMode) {
	if (!oldItemId || !itemId) return false;

	var itemNd = this.getItemById('', itemId, 0);
	if (!itemNd) return false;

	if (editMode === undefined || editMode.search(/^view$|^edit$/) === -1) {
		if (this.isTempID(itemId) || this.getNodeElement(itemNd, 'locked_by_id') === this.getCurrentUserID())
			editMode = 'edit';
		else editMode = 'view';
	}

	viewMode = viewMode || "tab view";

	return this.uiReShowItemEx(oldItemId, itemNd, viewMode);
};

Aras.prototype.uiViewXMLInFrame = function Aras_uiViewXMLInFrame(frame, xmldoc, expandNodes) {
	if (!frame) return;
	var xsldoc = this.createXMLDocument();
	var baseUrl = this.getBaseURL();
	xsldoc.load(baseUrl + '/styles/default.xsl');
	try {
		//TODO: there should be a better way to check if method setProperty is supported on xsldoc
		xsldoc.setProperty("SelectionNamespaces", 'xmlns:xsl="http://www.w3.org/1999/XSL/Transform"');
	}
	catch (excep) {
	}
	xsldoc.selectSingleNode("./xsl:stylesheet/xsl:param").setAttribute("select", "boolean('" + expandNodes + "')");
	frame.document.write(xmldoc.transformNode(xsldoc));
};

Aras.prototype.uiViewXMLstringInFrame = function Aras_uiViewXMLstringInFrame(frame, string, expandNodes) {
	if (!frame) return;
	var xmldoc = this.createXMLDocument();
	xmldoc.loadXML(string);

	this.uiViewXMLInFrame(frame, xmldoc, expandNodes);
};

Aras.prototype.uiFieldGetValue = function (uiField) {
	var uiForm = uiField.form;
	var name = uiField.name;
	var type = uiField.type;
	var value = null,
		i;

	if (uiField.field_type === 'item') value = uiField.internal_value;
	else if (type.search(/^text|^hidden$/) === 0) {
		if (uiField.internal_value) value = uiField.internal_value;
		else value = uiField.value;
	}
	else if (type === 'password') {
		if (uiField.pwdChanged === 1) value = calcMD5(uiField.value);
		else value = uiField.internal_value;
	}
	else if (type === 'checkbox') value = (uiField.checked) ? 1 : 0;
	else if (type === 'select-one') {
		if (uiField.selectedIndex !== -1) value = uiField.options[uiField.selectedIndex].value;
	}
	else if (type === 'radio') {///SNNicky: check!!!!!
		value = '';
		for (i = 0; i < uiForm[name].length; i++) {
			if (uiForm[name][i].checked) {
				value = uiForm[name][i].value;
				break;
			}
		}
	}
	else if (type === 'checkbox_group') {
		value = '';
		for (i = 0; i < uiForm[name].length; i++) {
			if (uiForm[name][i].checked) {
				if (value !== '') value += ',';
				value += uiForm[name][i].value;
			}
		}
	}
	this.AlertError(name + ":" + value, "", ""); //what does this do??
	return value;
};

Aras.prototype.getvisiblePropsForItemType = function Aras_getVisiblePropsForItemType(currItemType) {
	var itemTypeName = this.getItemProperty(currItemType, 'name');
	var itemTypeId = currItemType.getAttribute('id');
	var nodes_tmp = [];
	var cols = this.getPreferenceItemProperty("Core_GlobalLayout", null, "col_order"),
		i;

	var visiblePropNds = currItemType.selectNodes(this.getVisiblePropertiesXPath(itemTypeName));

	if (cols) {
		cols = cols.split(';');

		if (visiblePropNds.length === cols.length || visiblePropNds.length + 1 === cols.length) {
			for (i = 0; i < visiblePropNds.length; i++) {
				var propNm = this.getItemProperty(visiblePropNds[i], 'name');
				for (var j = 0; j < cols.length; j++) {
					if ((propNm + "_D") === cols[j]) {
						nodes_tmp[j] = visiblePropNds[i];
						break;
					}
				}
				if (j === cols.length) {
					cols = null;
					break;
				}
			}
		}
		else {
			cols = null;
		}
	}
	if (!cols) {
		visiblePropNds = this.sortProperties(visiblePropNds);
	}
	else {
		visiblePropNds = [];
		for (i = 0; i < nodes_tmp.length; i++) {
			if (nodes_tmp[i] !== undefined)
				visiblePropNds.push(nodes_tmp[i]);
		}
	}

	return visiblePropNds;
};

Aras.prototype.uiInitItemsGridSetups = function Aras_uiInitItemsGridSetups(currItemType, visibleProps) {
	var itemTypeName = this.getItemProperty(currItemType, 'name');
	var itemTypeId = currItemType.getAttribute('id'),
		i;

	const xProperties = currItemType.selectNodes('Relationships/Item[@type=\'xItemTypeAllowedProperty\' and not(inactive=\'1\')]/related_id/Item[@type=\'xPropertyDefinition\']');
	var propLength = xProperties.length;
	for (i = 0; i < propLength; i++) {
		var prop = xProperties[i];
		visibleProps.push(prop);
	}

	if (!itemTypeName) return null;
	var self = this;
	//  var _itemTypeName_ = itemTypeName.replace(/\s/g, '_');

	var varsHash = {};

	var gridSetups = this.sGridsSetups[itemTypeName];
	if (!gridSetups) {
		gridSetups = this.newObject();
		this.sGridsSetups[itemTypeName] = gridSetups;
	}

	var colWidths = this.getPreferenceItemProperty('Core_ItemGridLayout', itemTypeId, 'col_widths');
	var colOrder = this.getPreferenceItemProperty('Core_ItemGridLayout', itemTypeId, 'col_order');

	var flg = ((colWidths === null || colWidths === "") ||
	(colOrder === null || colOrder === "") ||
	(colWidths.split(";").length !== colOrder.split(";").length));

	function CheckCorrectColumnsInfo(arr, suffix) {
		if (!arr) return;

		for (var i = 0; i < arr.length; i++) {
			var colNm = self.getItemProperty(arr[i], "name") + "_" + suffix;
			var re = new RegExp("(^|;)" + colNm + "(;|$)");
			if (colOrder.search(re) === -1) {
				flg = true;
				break;
			}
			colOrder = colOrder.replace(re, "$1$2");
		}
	}

	if (!flg) {
		//check if already saved setups are valid
		colOrder = colOrder.replace(/(^|;)L($|;)/, "$1$2");

		if (!flg) CheckCorrectColumnsInfo(visibleProps, "D");
		if (!flg) {
			colOrder = colOrder.replace(/;/g, "");
			if (colOrder !== "") flg = true;
		}
	}

	if (flg) {
		colOrder = this.newArray();
		colWidths = this.newArray();
		colOrder[0] = "L";
		colWidths[0] = 32;

		for (i = 0; i < visibleProps.length; i++) {
			var visibleProp = visibleProps[i];
			var name = this.getItemProperty(visibleProp, "name") + "_D";
			var width;
			if (name.startsWith('xp-')) {
				width = 0;
			} else {
				width = parseInt(this.getItemProperty(visibleProp, "column_width"));
				if (isNaN(width) || width === 0) width = 100;
			}

			colOrder.push(name);
			colWidths.push(width);
		}

		varsHash.col_widths = colWidths.join(";");
		varsHash.col_order = colOrder.join(";");
	}
	else {
		colWidths = colWidths.split(';');
		flg = false;

		//check for zero-width columns
		for (i = 0; i < colWidths.length; i++) {
			var newVal = parseInt(colWidths[i]);
			if (isNaN(newVal) || newVal < 0) {
				newVal = (i === 0 ? 32 : parseInt(this.getItemProperty(visibleProps[i - 1], 'column_width')));
				if (isNaN(newVal) || newVal <= 0) newVal = 100;
				colWidths[i] = newVal;
				flg = true;
			}
		}

		if (flg) {
			varsHash.col_widths = colWidths.join(";");
		}
	}

	this.setPreferenceItemProperties("Core_ItemGridLayout", itemTypeId, varsHash);
};

Aras.prototype.uiInitRelationshipsGridSetups = function Aras_uiInitRelationshipsGridSetups(relationshiptypeID, Dprops, Rprops, grid_view) {
	if (!grid_view) {
		grid_view = "left";
	}

	var self = this,
		prop,
		i;

	var colWidths = this.getPreferenceItemProperty('Core_RelGridLayout', relationshiptypeID, 'col_widths');
	var colOrder = this.getPreferenceItemProperty('Core_RelGridLayout', relationshiptypeID, 'col_order');

	var flg = ((colWidths === null || colWidths === "") || (colOrder === null || colOrder === "") || (colWidths.split(";").length !== colOrder.split(";").length));

	function CheckCorrectColumnsInfo(arr, suffix) {
		if (!arr) return;

		for (var i = 0; i < arr.length; i++) {
			var colNm = self.getItemProperty(arr[i], "name") + "_" + suffix;
			var re = new RegExp("(^|;)" + colNm + "(;|$)");
			if (colOrder.search(re) === -1) {
				flg = true;
				break;
			}
			colOrder = colOrder.replace(re, "$1$2");
		}
	}

	function getColumnDefaultWidth(colNum) {
		var colNm = colOrder[colNum];
		if (colNm === "L") return 32;

		var DR = colNm.substr(colNm.length - 1);
		var propNm = colNm.substr(0, colNm.length - 2);

		var propArr = null;
		if (DR === "D") propArr = Dprops;
		else if (DR === "R") propArr = Rprops;

		if (propArr) {
			for (var i = 0; i < propArr.length; i++) {
				var prop = propArr[i];
				if (self.getItemProperty(prop, "name") === propNm) {
					var column_width = parseInt(self.getItemProperty(prop, "column_width"));
					if (isNaN(column_width)) {
						column_width = propNm.startsWith('xp-') ? 0 : 100;
					}
					return column_width;
				}
			}
		}

		return 100;
	}

	if (!flg) {
		//check if already saved setups are valid
		if (Rprops) colOrder = colOrder.replace(/(^|;)L($|;)/, "$1$2");

		if (!flg) CheckCorrectColumnsInfo(Dprops, "D");
		if (!flg) CheckCorrectColumnsInfo(Rprops, "R");
		if (!flg) {
			colOrder = colOrder.replace(/;/g, "");
			if (colOrder !== "") flg = true;
		}

		if (!flg) {
			colOrder = this.getPreferenceItemProperty('Core_RelGridLayout', relationshiptypeID, "col_order");
			colWidths = colWidths.split(';');
			flg = false;

			//check for zero-width columns
			for (i = 0; i < colWidths.length; i++) {
				var newVal = parseInt(colWidths[i]);
				if (isNaN(newVal) || newVal < 0) {
					newVal = getColumnDefaultWidth(i);
					colWidths[i] = newVal;
					flg = true;
				}
			}

			if (flg) this.setPreferenceItemProperties("Core_RelGridLayout", relationshiptypeID, { col_widths: colWidths.join(";") });

			return;
		}
	}

	colOrder = this.newArray();
	colWidths = this.newArray();
	if (Rprops) {
		colOrder[0] = "L";
		colWidths[0] = 32;
	}

	// +++ sort columns
	var Dpriority = 0, Rpriority = 0;
	if (grid_view === "left") {
		//related item goes first
		Dpriority = 1;
		Rpriority = 0;
	}
	else if (grid_view === "intermix") {
		Dpriority = 0;
		Rpriority = 0;
	}
	else {
		Dpriority = 0;
		Rpriority = 1;
	}

	var allPropsInfoArr = [];
	if (Dprops) {
		for (i = 0; i < Dprops.length; i++) {
			prop = Dprops[i];

			allPropsInfoArr.push(
			{
				name: this.getItemProperty(prop, "name") + "_D",
				width: this.getItemProperty(prop, "column_width"),
				sort_order: this.getItemProperty(prop, "sort_order"),
				default_search: this.getItemProperty(prop, "default_search"),
				priority: Dpriority
			});
		}
	}

	if (Rprops) {
		for (i = 0; i < Rprops.length; i++) {
			prop = Rprops[i];

			allPropsInfoArr.push(
			{
				name: this.getItemProperty(prop, "name") + "_R",
				width: this.getItemProperty(prop, "column_width"),
				sort_order: this.getItemProperty(prop, "sort_order"),
				default_search: this.getItemProperty(prop, "default_search"),
				priority: Rpriority
			});
		}
	}

	function sorterF(p1, p2) {
		var c1 = parseInt(p1.priority);
		var c2 = parseInt(p2.priority);

		if (c1 < c2) return -1;
		else if (c2 < c1) return 1;
		else {
			c1 = parseInt(p1.sort_order);
			c2 = parseInt(p2.sort_order);

			if (isNaN(c2)) return -1;
			if (isNaN(c1)) return 1;

			if (c1 < c2) return -1;
			else if (c2 < c1) return 1;
			else {
				c1 = p1.name;
				c2 = p2.name;

				if (c1 < c2) return -1;
				else if (c2 < c1) return 1;
				else return 0;
			}
		}
	}

	allPropsInfoArr = allPropsInfoArr.sort(sorterF);
	// --- sort columns

	for (i = 0; i < allPropsInfoArr.length; i++) {
		const propName = allPropsInfoArr[i].name;
		colOrder.push(propName);

		var width = parseInt(allPropsInfoArr[i].width);
		if (isNaN(width)) {
			width = propName.startsWith('xp-') ? 0 : 100;
		}
		colWidths.push(width);
	}

	this.setPreferenceItemProperties("Core_RelGridLayout", relationshiptypeID, { col_widths: colWidths.join(";"), col_order: colOrder.join(";") });
};

Aras.prototype.uiToggleCheckbox = function (uiField) {
	uiField.checked = uiField.checked ? false : true;
};

Aras.prototype.uiGenerateGridXML = function Aras_uiGenerateGridXML(inDom, Dprops, Rprops, typeID, params, getCached) {
	var key = this.MetadataCache.CreateCacheKey("uiGenerateGridXML", typeID);
	if (params) {
		for (var k in params) {
			//k can be undefined in IE9 if one of param keyes was empty string, i.e. params[""] = ""
			//evaluating value by index: params[""] gives right value, but evaluating it with 'for' gives undefined value.
			if (k) {
				var additionalParam = k;
				if (params[k]) additionalParam += "=" + params[k];
				key.push(additionalParam);
			}
		}
	}

	var xsl = this.MetadataCache.GetItem(key);
	if (xsl)
		xsl = xsl.content;

	var mainArasObj = this.findMainArasObject();
	if (xsl && (getCached === undefined || getCached === true)) {
	}
	else {
		var sXsl = this.uiGenerateGridXSLT(Dprops, Rprops, params, typeID);

		xsl = mainArasObj.createXMLDocument();
		xsl.loadXML(sXsl);
		var itemTypeNd = this.getItemTypeNodeForClient(typeID, "id");
		this.MetadataCache.SetItem(key, this.IomFactory.CreateCacheableContainer(xsl, itemTypeNd));
	}
	var res = inDom.transformNode(xsl);

	//replaces VaultURL by FullFileURL
	var self = this;
	var FixVaultUrl = function (str, srcTag, vaultPrefix, fileId, fullStr) {
		var fileUrl = self.IomInnovator.getFileUrl(fileId, self.Enums.UrlType.SecurityToken);
		fileUrl = self.browserHelper.escapeUrl(fileUrl);
		return srcTag + fileUrl + '"';
	};

	//replaces all "src" attributes starting with "vault:///"
	var FixImageCellSrc = function (str, offsetPos, fullStr) {
		return str.replace(/(src=")(vault:\/\/\/\?fileid\=)([^"]*)"/i, FixVaultUrl);
	};

	//search all <td> elements with attribute fdt="image"
	var resultXML = res.replace(/<td fdt="image"[^>]*?>.*?<\/td>/gi, FixImageCellSrc);

	//if font-size property exist we should limit cell height by line-height property
	resultXML = resultXML.replace(/(<td [^>]*? css=.*?)(font-size)/g, "$1line-height:15px; $2");

	return resultXML;
};

Aras.prototype.uiPrepareTableWithColumns = function Aras_uiPrepareTableWithColumns(inDom, columnObjects) {
	//columnObjects: {name, order, width}
	this.uiPrepareDOM4GridXSLT(inDom);

	var tableNd = inDom.selectSingleNode(this.XPathResult("/table"));
	tableNd.setAttribute("editable", "false");

	var columns = tableNd.selectSingleNode("columns");
	var inputrow = tableNd.selectSingleNode("inputrow");

	// make inputrow invisible by default.
	inputrow.setAttribute("visible", "false");

	for (var col in columnObjects) {
		var columnObject = columnObjects[col];
		var column = inDom.createElement("column");
		column.setAttribute("name", columnObject.name);
		column.setAttribute("order", columnObject.order);
		column.setAttribute("width", columnObject.width);
		columns.appendChild(column);
		var td = inDom.createElement("td");
		inputrow.appendChild(td);
	}
};

Aras.prototype.uiPrepareDOM4XSLT = function Aras_uiPrepareDOM4XSLT(inDom, itemTypeID, RTorITPrefix, colWidths, colOrder) {
	var prefTp = GetPrefixItemTypeName(RTorITPrefix);

	var colWidthsArr = colWidths ? colWidths.split(";") : this.getPreferenceItemProperty(prefTp, itemTypeID, "col_widths").split(";");
	var colOrderArr = colOrder ? colOrder.split(";") : this.getPreferenceItemProperty(prefTp, itemTypeID, "col_order").split(";");
	var columnObjects = {};
	for (var i = 0; i < colOrderArr.length; i++) {
		columnObjects[i] = { name: colOrderArr[i], order: i, width: colWidthsArr[i] };
	}
	this.uiPrepareTableWithColumns(inDom, columnObjects);

	function GetPrefixItemTypeName(prefix) {
		if (!prefix)
			prefix = 'IT_';

		var result;
		if (prefix === 'IT_') {
			result = 'Core_ItemGridLayout';
		}
		else {
			result = 'Core_RelGridLayout';
		}
		return result;
	}
};

Aras.prototype.uiGenerateItemsGridXML = function Aras_uiGenerateItemsGridXML(inDom, props, itemtypeID, params) {
	return this.uiGenerateGridXML(inDom, props, undefined, itemtypeID, params);
}; //uiGenerateItemsGridXML

Aras.prototype.uiGenerateRelationshipsGridXML = function Aras_uiGenerateRelationshipsGridXML(inDom, Dprops, Rprops, itemTypeId, params, getCached) {
	//itemTypeId is id of "is relationship" ItemType
	return this.uiGenerateGridXML(inDom, Dprops, Rprops, itemTypeId, params, getCached);
}; //uiGenerateRelationshipsGridXML

Aras.prototype.uiGenerateParametersGrid = function Aras_uiGenerateParametersGrid(itemTypeName, classification) {
	/*----------------------------------------
	* uiGenerateParametersGrid
	*
	* Purpose:
	* sends request to Innovator Server to generate xml for parameters grid for
	* specified ItemType and classification. Returns xml string.
	*
	* Arguments:
	* itemTypeName - name of ItemType
	* classification - classification of an Item
	*/

	var res = null;
	if (itemTypeName && classification) {
		var classificationDom = this.createXMLDocument();
		classificationDom.loadXML("<Item><classification /></Item>");
		classificationDom.documentElement.setAttribute("type", itemTypeName);
		classificationDom.selectSingleNode("Item/classification").text = classification;
		res = this.soapSend("GenerateParametersGrid", classificationDom.xml);
		res = res.getResult().selectSingleNode("table");
	}

	if (res) {
		var tmp = res.selectSingleNode("thead");
		var pNd = tmp.selectSingleNode("th[.='Property']");
		if (pNd) pNd.text = this.getResource("", "advanced_search.property");

		var vNd = tmp.selectSingleNode("th[.='Value']");
		if (vNd) vNd.text = this.getResource("", "ui_methods.value");
		res = res.xml;
	}
	else {
		var emptyTableXML =
    "<table editable='true' font='Arial-8' draw_grid='true' enableHtml='false' enterAsTab='false' bgInvert='false' " +
    " onStart='onGridLoad' onEditCell='onParamsGridCellEdit' onXMLLoaded='onXmlLoaded' " +
    " onKeyPressed='onGridKeyPressed' >" +
    "<thead>" +
    " <th align='center'>" + this.getResource("", "advanced_search.property") + "</th>" +
    " <th align='center'>" + this.getResource("", "ui_methods.value") + "</th>" +
	" <th align='center'>" + this.getResource("", "parametersgrid.sort_order") + "</th>" +
    "</thead>" +
    "<columns>" +
    " <column width='20%' edit='NOEDIT' align='left' order='0'/>" +
    " <column width='70%' edit='FIELD' align='left' order='1'/>" +
	" <column width='10%' edit='NOEDIT' align='left' order='2'/>" +
    "</columns>" +
    "</table>";

		res = emptyTableXML;
	}

	var resDom = this.createXMLDocument();
	resDom.loadXML(res);

	return resDom;
};

Aras.prototype.uiIsParamTabVisible = function Aras_uiIsParamTabVisible(itemNd, itemTypeName) {
	var paramTabProperties = this.uiIsParamTabVisibleEx(itemNd, itemTypeName);
	return paramTabProperties.show;
};

Aras.prototype.uiGenerateRelationshipsTabbar = function Aras_uiGenerateRelationshipsTabbar(itemTypeName, itemID) {
	var res = null;
	var itemType;
	if (itemTypeName) itemType = this.getItemTypeNodeForClient(itemTypeName);
	if (itemType && itemTypeName && itemID) {
		var cachedTabbar = this.getItemProperty(itemType, "relationships_tabbar_xml");
		if (cachedTabbar && cachedTabbar.indexOf("<exclusions") < 0) {
			res = { xml: cachedTabbar };
		}
		else {
			res = this.soapSend("GenerateRelationshipsTabbar", "<Item type='" + itemTypeName + "' id='" + itemID + "'/>");
			res = res.getResult().selectSingleNode("tabbar");
		}
	}

	if (res) {
		res = res.xml;
	}
	else {
		var emptyTableXML = "<tabbar/>";

		res = emptyTableXML;
	}

	var resDom = this.createXMLDocument();
	resDom.loadXML(res);

	return resDom;
};

Aras.prototype.uiGenerateRelationshipsTable = function Aras_uiGenerateRelationshipsTable(itemTypeName, itemID, relationshiptypeID) {
	var res = null;
	if (itemTypeName && itemID) {
		res = this.soapSend("GenerateRelationshipsTable", "<Item type='" + itemTypeName + "' id='" + itemID + "' relationshiptype='" + relationshiptypeID + "'/>");
		res = res.getResult().xml;
	}
	else {
		res = "<Result />";
	}

	var resDom = this.createXMLDocument();
	resDom.loadXML(res);

	return resDom;
};

Aras.prototype.uiPrepareDOM4GridXSLT = function Aras_uiPrepareDOM4GridXSLT(dom) {
	/*
	adds <table editable="true"><columns /><inputrow/></table> to Envelope Body Result.

	removes previous entry <table> entry
	*/
	var res = dom.selectSingleNode(this.XPathResult());
	var tableNd = res.selectSingleNode("table");
	if (tableNd) res.removeChild(tableNd);

	tableNd = res.appendChild(dom.createElement("table"));
	tableNd.appendChild(dom.createElement("columns"));
	tableNd.appendChild(dom.createElement("inputrow"));
};

Aras.prototype.uiGenerateGridXSLT = function Aras_uiGenerateGridXSLT(DescByProps_Arr, RelatedProps_Arr, params, typeID) {
	var self = this;

	if (params === undefined) {
		params = {};
	}

	var itemTypeName = this.getItemTypeName(typeID);
	var showLockColumn = Boolean((RelatedProps_Arr === undefined) || RelatedProps_Arr);
	var table_xpath = self.XPathResult("/table");
	var enable_links = (params.enable_links === undefined || params.enable_links === true);
	var enableFileLinks = Boolean(params.enableFileLinks);
	var generateOnlyRows = (true === params.only_rows);
	var params_bgInvert = (params.bgInvert === undefined || params.bgInvert === false) ? "false" : "true";

	var columnsXSLT = [];
	var theadXSLT = [];
	var listsXSLT = [];

	// +++ create header row
	function AddHeaderColumn(name, header) {
		theadXSLT.push("<xsl:if test=\"column[@name='" + name + "']\">");
		theadXSLT.push("  <th align=\"c\">" + self.escapeXMLAttribute(header) + "</th>");
		theadXSLT.push("</xsl:if>");
	}

	function AddHeaderColumns(propsArr, suffix) {
		var f2Header = ' [...]';

		if (!propsArr) return;
		for (var i = 0; i < propsArr.length; i++) {
			var prop = propsArr[i];
			var propName = self.getItemProperty(prop, "name");
			var header = self.getItemProperty(prop, "label");
			if (header === "") header = propName;

			var dataType = self.getItemProperty(prop, "data_type");
			if (dataType === 'item') {
				var propDS = self.getItemProperty(prop, 'data_source');
				if (propDS) {
					var it = self.getItemTypeName(propDS);
					if (it) header += f2Header;
				}
			}
			else if (dataType === 'date' || dataType === 'text' || dataType === 'image' || dataType === 'formatted text' || dataType === 'color') {
				header += f2Header;
			}

			AddHeaderColumn(propName + suffix, header);
		}
	}

	if (!generateOnlyRows) {
		theadXSLT.push("<thead>");

		if (showLockColumn) AddHeaderColumn("L", "");

		AddHeaderColumns(DescByProps_Arr, "_D");

		AddHeaderColumns(RelatedProps_Arr, "_R");

		theadXSLT.push("</thead>");
		// --- create header row
	}

	var lists = this.newObject();
	var reservedListsNum = 2; //because we reserve 2 lists for special needs (e.g. build properties list for filter list pattern in relationships grid)
	var listNum = reservedListsNum - 1;
	var i;

	// +++ create columns
	function AddColumn(name, d_width, edit, align, sortStr, bgInvert, password, textColorInvert, flyWeightType, dataSourceName) {
		columnsXSLT.push("<xsl:if test=\"column[@name='" + name + "']\">");
		columnsXSLT.push("<column ");

		if (d_width) {
			columnsXSLT.push("width=\"" + d_width + "\" ");
		}
		if (edit) {
			columnsXSLT.push("edit='" + edit + "' ");
		}
		if (align) {
			columnsXSLT.push("align='" + align + "' ");
		}
		if (bgInvert) {
			columnsXSLT.push("bginvert='" + bgInvert + "' ");
		}
		if (password) {
			columnsXSLT.push("password='" + password + "' ");
		}
		if (textColorInvert) {
			columnsXSLT.push("textcolorinvert='" + textColorInvert +  "' ");
		}
		if (name) {
			columnsXSLT.push("colname='" + name +  "' ");
		}
		if (flyWeightType) {
			columnsXSLT.push("type='" + flyWeightType +  "' ");
		}
		if (dataSourceName) {
			columnsXSLT.push("dataSourceName='" + dataSourceName +  "' ");
		}
		if (sortStr) {
			columnsXSLT.push(sortStr);
		}

		columnsXSLT.push(">");
		columnsXSLT.push("<xsl:variable name=\"width\" select=\"column[@name='" + name + "']/@width\"/>");
		columnsXSLT.push("<xsl:variable name=\"order\" select=\"column[@name='" + name + "']/@order\"/>");
		columnsXSLT.push("<xsl:if test=\"$width\">");
		columnsXSLT.push("<xsl:attribute name=\"width\"><xsl:value-of select=\"$width\"/></xsl:attribute>");
		columnsXSLT.push("</xsl:if>");
		columnsXSLT.push("<xsl:if test=\"$order\">");
		columnsXSLT.push("<xsl:attribute name=\"order\"><xsl:value-of select=\"$order\"/></xsl:attribute>");
		columnsXSLT.push("</xsl:if>");
		columnsXSLT.push("</column>");
		columnsXSLT.push("</xsl:if>");
	}

	function AddColumns(propsArr, suffix) {
		if (!propsArr) return;

		for (var i = 0; i < propsArr.length; i++) {
			var prop = propsArr[i],
				propName = self.getItemProperty(prop, "name"),
				header = self.getItemProperty(prop, "label") || propName,
				data_type = self.getItemProperty(prop, "data_type"),
				isForeign = (data_type === "foreign"),
				isInBasketTask = (typeID === self.getItemTypeId("InBasket Task")),
				column_width = self.getItemProperty(prop, "column_width") || "100",
				column_alignment = self.getItemProperty(prop, "column_alignment"),
				locale = ' locale="' + self.getSessionContextLocale() + '"',
				bgInvert, textColorInvert, password, flyWeightType,
				format = "", sortStr = "", editStr = "";

			column_alignment = column_alignment ? column_alignment.charAt(0) : "1";

			if (isForeign) {
				var sourceProperty = self.uiMergeForeignPropertyWithSource(prop, true);
				if (sourceProperty) {
					prop = sourceProperty;
					data_type = self.getItemProperty(prop, "data_type");
				}
			}

			if (data_type.search(/list$/) != -1) {
				var listInfo = self.newObject();
				listInfo.listID = self.getItemProperty(prop, "data_source");
				listInfo.listType = data_type;

				listNum++;
				lists[listNum] = listInfo;
				editStr = ((data_type == "mv_list") ? "MV_LIST:" : "COMBO:") + listNum;
			}
			else {
				editStr = "FIELD";
			}

			switch (data_type) {
				case "date":
					format = self.getItemProperty(prop, "pattern");
					format = self.getDotNetDatePattern(format) || "MM/dd/yyyy";
					editStr = "dateTime";
					sortStr = 'sort="DATE" inputformat="' + format + '"' + locale;
					break;
				case "decimal":
					format = self.getDecimalPattern(self.getItemProperty(prop, "prec"), self.getItemProperty(prop, "scale"));
					sortStr = 'sort="NUMERIC"' + ((format) ? ' inputformat="' + format + '"' : "") + locale;
					break;
				case "integer":
				case "float":
					sortStr = 'sort="NUMERIC"' + ((format) ? ' inputformat="' + format + '"' : "") + locale;
					break;
				case "ubigint":
				case "global_version":
					sortStr = 'sort="UBIGINT"' + ((format) ? ' inputformat="' + format + '"' : "") + locale;
					break;
				case "color list":
				case "color":
					bgInvert = "false";
					textColorInvert = "true";
					break;
				case "md5":
					password = "true";
					break;
				case "image":
					flyWeightType = "IMAGE";
					break;
				case "item":
					var dataSource = self.getItemProperty(prop, "data_source"),
						dataSourceName = dataSource ? self.getItemTypeName(dataSource) : "";

					if (dataSourceName == "File") {
						editStr = "File";
					}
					else if (!isForeign) {
						editStr = "InputHelper";
					}
					break;
				default:
					break;
			}

			if (isInBasketTask  && ("start_date" === propName || "due_date" === propName)) {
				bgInvert = "false";
				textColorInvert = "true";
			}

			AddColumn(propName + suffix, column_width, editStr, column_alignment, sortStr, bgInvert, password, textColorInvert, flyWeightType, dataSourceName);
			dataSourceName = null;
		}
	}

	if (!generateOnlyRows) {
		let lockColumnListIndex;

		columnsXSLT.push("<columns>");
			if (showLockColumn) {
				lockColumnListIndex = ++listNum;
				AddColumn("L", "32", "COMBO:" + lockColumnListIndex, "c", "");
			}
			AddColumns(DescByProps_Arr, "_D");
			AddColumns(RelatedProps_Arr, "_R");
		columnsXSLT.push("</columns>");
		// --- create columns

		// +++ create lists
		//reserve reservedListsNum lists for special needs
		for (let idx = 0; idx < reservedListsNum; idx++) {
			listsXSLT.push("<list id=\"" + idx + "\"/>");
		}

		if (showLockColumn) {
			const imageStyle = 'margin-right: 4px; height: auto; width: auto; max-width: 20px; max-height: 20px;';
			const resoucePrefix = 'claimed';
			const valuesList = ["",
				"<img src='../images/ClaimOn.svg' style='" + imageStyle + "' />",
				"<img src='../images/ClaimOther.svg' style='" + imageStyle + "' />",
				"<img src='../images/ClaimAnyone.svg' style='" + imageStyle + "' />"];
			const optionsList = ["<span style='padding: 0 22px;'>" + this.getResource('', 'itemsgrid.locked_criteria_ppm.clear_criteria') + "</span>",
					"<img src='../images/ClaimOn.svg' align='left' style='" + imageStyle + "' />" + this.getResource("", "itemsgrid.locked_criteria_ppm." + resoucePrefix + "_by_me"),
					"<img src='../images/ClaimOther.svg' align='left' style='" + imageStyle + "' />" + this.getResource("", "itemsgrid.locked_criteria_ppm." + resoucePrefix + "_by_others"),
					"<img src='../images/ClaimAnyone.svg' align='left' style='" + imageStyle + "' />" + this.getResource("", "itemsgrid.locked_criteria_ppm." + resoucePrefix + "_by_anyone")];

			listsXSLT.push("<list id=\"" + lockColumnListIndex + "\">");
				for (i = 0; i < optionsList.length; i++) {
					listsXSLT.push("<listitem value=\"" + this.escapeXMLAttribute(valuesList[i]) + "\" label=\"" + this.escapeXMLAttribute(optionsList[i]) + "\" />");
				}
			listsXSLT.push("</list>");
		}
	}

	//prepare to request all lists values
	var reqListsArr = this.newArray();
	for (var listIdx in lists) {
		var listInfo = lists[listIdx];
		var relType;
		if (listInfo.listType == "filter list") {
			relType = "Filter Value";
		}
		else {
			relType = "Value";
		}

		var listDescr = this.newObject();
		listDescr.id = listInfo.listID;
		listDescr.relType = relType;

		reqListsArr.push(listDescr);
	}

	if (reqListsArr.length > 0) {
		var resLists = this.getSeveralListsValues(reqListsArr);

		for (var listNum2 in lists) {
			var listInfo2 = lists[listNum2];

			listsXSLT.push("<list id=\"" + listNum2 + "\">");
			if (listInfo2.listType != "mv_list") {
				listsXSLT.push("<listitem value=\"\" label=\"\" />");
			}

			var listVals = resLists[listInfo2.listID];
			if (listVals) {
				for (i = 0; i < listVals.length; i++) {
					var valNd = listVals[i];
					var val = this.getItemProperty(valNd, "value");
					var lab = this.getItemProperty(valNd, "label");
					if (lab === "") lab = val;
					val = this.escapeXMLAttribute(val);
					lab = this.escapeXMLAttribute(lab);
					listsXSLT.push("<listitem value=\"" + val + "\" label=\"" + lab + "\" />");
				}
			}
			listsXSLT.push("</list>");
		}
	}
	// --- create lists

	var resXSLTArr = [];
	resXSLTArr.push(
		"<xsl:stylesheet version=\"1.0\" " +
		"xmlns:xsl=\"http://www.w3.org/1999/XSL/Transform\" " +
		"xmlns:msxsl=\"urn:schemas-microsoft-com:xslt\" " +
		"xmlns:aras=\"http://www.aras.com\" ");

	this.browserHelper.addXSLTSpecialNamespaces(resXSLTArr);
	resXSLTArr.push(">\n");
	this.browserHelper.addXSLTCssFunctions(resXSLTArr);

	resXSLTArr.push(
		"<xsl:output method=\"xml\" version=\"1.0\" omit-xml-declaration=\"yes\" cdata-section-elements=\"td\" encoding=\"UTF-8\"/>" +
		"<xsl:template match=\"text()|@*\">\n" +
		"  <xsl:value-of select=\".\"/>\n" +
		"</xsl:template>\n" +
		"<xsl:template match=\"/\">\n" +
		"<table editable=\"true\" " +
		"itemTypeID=\"" + typeID + "\" " +
		"font=\"Dialog-8\" enableHTML=\"false\" " +
		"link_func=\"onLink\" draw_grid=\"true\" multiselect=\"true\" column_draggable=\"true\" " +
		"enterAsTab=\"false\" bgInvert=\"" + params_bgInvert + "\" onClick=\"onSelectItem\" onDoubleClick=\"onDoubleClick\" " +
		"onStart=\"onGridAppletLoad\" onEditCell=\"onEditCell\" onMenuInit=\"onMenuCreate\" " +
		"onMenuClick=\"onMenuClicked\" onXMLLoaded=\"onXmlLoaded\" onKeyPressed=\"onKeyPressed\">" +
		"<xsl:apply-templates select=\"//Result\" />\n" +
		"</table>\n" +
		"</xsl:template>\n" +
		"<xsl:template match=\"columns\">\n" +
		theadXSLT.join("") +
		columnsXSLT.join("") +
		"</xsl:template>\n");

	if (!generateOnlyRows) {
		resXSLTArr.push(
			"<xsl:template match=\"inputrow\">\n" +
			"	<inputrow visible=\"{@visible}\" bgColor=\"#BDDEF7\">\n" +
			"		<xsl:for-each select=\"td\">\n" +
			"			<td/>\n" +
			"		</xsl:for-each>\n" +
			"	</inputrow>\n" +
			"</xsl:template>\n");
	}

	resXSLTArr.push(
		"<xsl:template match=\"Result\">\n" +
		"	<xsl:variable name=\"isEditable\" select=\"table/@editable\"/>\n" +
		"	<xsl:if test=\"$isEditable != ''\">\n" +
		"		<xsl:attribute name=\"editable\">\n" +
		"			<xsl:value-of select=\"$isEditable\"/>\n" +
		"		</xsl:attribute>\n" +
		"	</xsl:if>\n" +
		"<xsl:apply-templates select=\"table/columns\"/>\n" +
		listsXSLT.join("") +
		"<xsl:apply-templates select=\"table/inputrow\" />\n" +
		"<xsl:apply-templates select=\"Item\">\n" +
		"	<xsl:with-param name=\"hasLockedByIdColumn\" select=\"table/columns[count(columns) = 0] or table/columns/column[@name='L']\"/>\n" +
		"</xsl:apply-templates>\n" +
		"</xsl:template>\n" +
		"<xsl:template match=\"Item\">\n" +
		"	<xsl:param name=\"hasLockedByIdColumn\"/>\n" +
		"		<xsl:variable name=\"item-CSS\">\n" +
		"			<xsl:choose>\n" +
		"				<xsl:when test=\"string(css) != '' or string(fed_css) != ''\">\n");

	this.browserHelper.addXSLTInitItemCSSCall(resXSLTArr, "string(css)", "string(fed_css)");

	resXSLTArr.push(
		"				</xsl:when>\n" +
		"				<xsl:otherwise>\n" +
		"					<xsl:value-of select=\"''\"/>\n" +
		"				</xsl:otherwise>\n" +
		"			</xsl:choose>\n" +
		"		</xsl:variable>\n");

	if (RelatedProps_Arr) {
		resXSLTArr.push(
			"		<xsl:variable name=\"rItem-CSS\">\n" +
			"			<xsl:choose>\n" +
			"				<xsl:when test=\"string(related_id/Item/css) != '' or string(related_id/Item/fed_css) != ''\">\n");

		this.browserHelper.addXSLTInitItemCSSCall(resXSLTArr, "string(related_id/Item/css)", "string(related_id/Item/fed_css)");

		resXSLTArr.push(
			"				</xsl:when>\n" +
			"				<xsl:otherwise>\n" +
			"					<xsl:value-of select=\"''\"/>\n" +
			"				</xsl:otherwise>\n" +
			"			</xsl:choose>\n" +
			"		</xsl:variable>\n");
	}

	resXSLTArr.push(
		"<tr id=\"{@id}\" action=\"{@id}\">\n" +
		"	<xsl:if test=\"boolean(@action='purge' or @action='delete')\">\n" +
		"		<xsl:attribute name=\"textColor\">\n" +
		"			<xsl:value-of select=\"'#B0B0B0'\"/>\n" +
		"		</xsl:attribute>\n" +
		"		<xsl:attribute name=\"font\">\n" +
		"			<xsl:value-of select=\"'Arial-italic-8'\"/>\n" +
		"		</xsl:attribute>\n" +
		"	</xsl:if>\n");

	// +++ lock icon
	if (showLockColumn) {
		resXSLTArr.push("<xsl:if test=\"$hasLockedByIdColumn\">\n");
		resXSLTArr.push("<td>");

		if (RelatedProps_Arr) {
			resXSLTArr.push("<xsl:if test=\"not(related_id/Item) and (not(related_id) or related_id='')\">&lt;img src='../images/NullRelated.svg'/&gt;</xsl:if>");
			resXSLTArr.push("<xsl:if test=\"related_id/Item\"><xsl:for-each select=\"related_id/Item\">");
		}

		var currentUserID = this.getCurrentUserID();
		resXSLTArr.push(
			"<xsl:variable name=\"isTemp\" select=\"boolean(@isTemp = '1')\"/>\n" +
			"<xsl:variable name=\"isDirty\" select=\"boolean(@isDirty = '1')\"/>\n" +
			"<xsl:variable name=\"locked_by_id\" select=\"string(locked_by_id)\"/>\n" +
			"<xsl:choose>\n" +
			"	<xsl:when test=\"$isTemp or $locked_by_id != '' or @discover_only='1'\">" +
			"		<xsl:choose>" +
			"			<xsl:when test=\"@discover_only='1'\">&lt;img src='../images/Blocked.svg'/&gt;</xsl:when>\n" +
			"			<xsl:otherwise>\n" +
			"				<xsl:if test=\"$isTemp\">&lt;img src='../images/New.svg'/&gt;</xsl:if>\n" +
			"				<xsl:if test=\"not($isTemp) and ($locked_by_id='" + currentUserID + "' or locked_by_id/Item[@id='" + currentUserID + "'])\">" +
			"					<xsl:if test=\"not($isDirty)\">&lt;img src='../images/ClaimOn.svg'/&gt;</xsl:if>" +
			"					<xsl:if test=\"$isDirty\">&lt;img src='../images/Edit.svg'/&gt;</xsl:if>" +
			"				</xsl:if>" +
			"				<xsl:if test=\"not($isTemp) and $locked_by_id != '" + currentUserID + "' and not(locked_by_id/Item[@id='" + currentUserID + "']) and $locked_by_id != ''\">&lt;img src='../images/ClaimOther.svg'/&gt;</xsl:if>" +
			"			</xsl:otherwise>" +
			"		</xsl:choose>" +
			"	</xsl:when>" +
			"	<xsl:otherwise>&lt;img src=''/&gt;</xsl:otherwise>" +
			"</xsl:choose>");

		if (RelatedProps_Arr)
			resXSLTArr.push("</xsl:for-each></xsl:if>");

		resXSLTArr.push("</td>\n");
		resXSLTArr.push("</xsl:if>");
	}
	// --- lock icon

	// ==== grid rows ===
	function GenerateRows(propsArr, xpath_prefix, special_td_attributes, cellCSSVariableName1) {
		if (!propsArr) return;

		var propItem, name, xpath,
			dataType, dataSource, dataSourceName,
			restrictedMsgCondition, i;

		for (i = 0; i < propsArr.length; ++i) {
			propItem = propsArr[i];
			name = self.getItemProperty(propItem, "name");
			xpath = xpath_prefix + name;
			dataType = self.getItemProperty(propItem, "data_type");
			restrictedMsgCondition = xpath + "[@is_null='0' and string(.)='']" + (xpath_prefix ? " or related_id[@is_null='0' and string(.)='']" : "");

			if ("foreign" == dataType) {
				var sourceProperty = self.uiMergeForeignPropertyWithSource(propItem);

				if (sourceProperty) {
					propItem = sourceProperty;
					dataType = self.getItemProperty(propItem, "data_type");
				}
			}

			resXSLTArr.push("<td fdt=\"" + dataType + "\" " + special_td_attributes + ">");
			resXSLTArr.push("<xsl:variable name=\"IsRestricted\" select=\"boolean(" + restrictedMsgCondition + ")\"/>");

			if ("item" == dataType || "color" == dataType || "color list" == dataType) {
				resXSLTArr.push("<xsl:if test=\"" + xpath + "\">");

				if ("item" == dataType) {
					dataSource = propItem.selectSingleNode("data_source");
					dataSourceName = dataSource ? dataSource.getAttribute("name") : "";

					if (enable_links || (enableFileLinks && dataSourceName == "File")) {
						var linkItemType = dataSourceName ? "'" + dataSourceName + "'" : "string(" + xpath + "/@type)";

						resXSLTArr.push(
							"<xsl:if test=\"not(" + xpath + "/@discover_only='1' or " + xpath + "/Item/@discover_only='1')\">\n" +
							"	<xsl:attribute name=\"link\">\n" +
							"		<xsl:choose>" +
							"			<xsl:when test=\"" + xpath + "!='' and not(" + xpath + "/Item)\">\n" +
							"				<xsl:text>'</xsl:text>\n" +
							"				<xsl:choose>\n" +
							"					<xsl:when test=\"" + xpath_prefix + "data_type='list' or " + xpath_prefix + "data_type='filter list' or " + xpath_prefix + "data_type='color list'\">\n" +
							"						<xsl:value-of select=\"'List'\"/>\n" +
							"					</xsl:when>\n" +
							"					<xsl:when test=\"" + xpath_prefix + "data_type='sequence'\">\n" +
							"						<xsl:value-of select=\"'Sequence'\"/>\n" +
							"					</xsl:when>\n" +
							"					<xsl:otherwise>\n" +
							"						<xsl:value-of select=\"" + linkItemType + "\"/>\n" +
							"					</xsl:otherwise>\n" +
							"				</xsl:choose>\n" +
							"				<xsl:text>','</xsl:text>\n" +
							"				<xsl:value-of select=\"" + xpath + "\"/>\n" +
							"				<xsl:text>'</xsl:text>\n" +
							"			</xsl:when>\n" +
							"			<xsl:when test=\"" + xpath + "/Item\">\n" +
							"				<xsl:text>'</xsl:text>\n" +
							"				<xsl:choose>\n" +
							"					<xsl:when test=\"" + xpath_prefix + "data_type='list' or " + xpath_prefix + "data_type='filter list' or " + xpath_prefix + "data_type='color list'\">\n" +
							"						<xsl:value-of select=\"'List'\"/>\n" +
							"					</xsl:when>\n" +
							"					<xsl:when test=\"" + xpath_prefix + "data_type='sequence'\">\n" +
							"						<xsl:value-of select=\"'Sequence'\"/>\n" +
							"					</xsl:when>\n" +
							"					<xsl:otherwise>\n" +
							"						<xsl:value-of select=\"" + linkItemType + "\"/>\n" +
							"					</xsl:otherwise>\n" +
							"				</xsl:choose>\n" +
							"				<xsl:text>','</xsl:text>\n" +
							"				<xsl:value-of select=\"" + xpath + "/Item/@id\"/>\n" +
							"				<xsl:text>'</xsl:text>\n" +
							"			</xsl:when>\n" +
							"		</xsl:choose>" +
							"	</xsl:attribute>\n" +
							"</xsl:if>");

						if (dataSourceName === "File")
						{
							resXSLTArr.push(
							"<xsl:if test=\"not(" + xpath + "/@discover_only='1' or " + xpath + "/Item/@discover_only='1')\">\n" +
							"	<xsl:if test=\"" + xpath + "/Item\">\n" +
							"		<xsl:attribute name=\"action\">\n" +
							"			<xsl:value-of select=\"" + xpath + "/Item/@action\"/>\n" +
							"		</xsl:attribute>\n" +
							"		<xsl:attribute name=\"filename\">\n" +
							"			<xsl:value-of select=\"" + xpath + "/Item/filename\"/>\n" +
							"		</xsl:attribute>\n" +
							"	</xsl:if>\n" +
							"</xsl:if>");
						}
					}
				}
				else if ("color" == dataType || "color list" == dataType) {
					resXSLTArr.push(
						"<xsl:variable name=\"goodColor\" select=\"'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890'\"/>" +
						"<xsl:if test=\"starts-with(" + xpath + ", '#') and string-length(translate(" + xpath + ", $goodColor, '')) = 1 and string-length(" + xpath + ") = 7\">" +
						"	<xsl:attribute name=\"bgColor\">" +
						"		<xsl:value-of select=\"" + xpath + "\"/>" +
						"	</xsl:attribute>" +
						"</xsl:if>");
				}

				resXSLTArr.push("</xsl:if>");
			}

			var nameCSS = name + "--CSS";
			resXSLTArr.push("<xsl:if test=\"contains(string($" + cellCSSVariableName1 + "), '." + name + "')\">");
			self.browserHelper.addXSLTGetPropertyStyleExCall(resXSLTArr, nameCSS, cellCSSVariableName1, name);

			resXSLTArr.push(
				"<xsl:attribute name=\"css\">" +
				"	<xsl:value-of select=\"substring($" + nameCSS + ", 2, string-length($" + nameCSS + ") - 2)\" />" + //remove first and last characters
				"</xsl:attribute>" +
				"	<xsl:if test=\"contains($" + nameCSS + ", ';font:')\">" +
				"		<xsl:variable name=\"font\" select=\"substring-before(substring-after($" + nameCSS + ", ';font:'), ';')\" />" +
				"		<xsl:if test=\"$font!=''\"><xsl:attribute name=\"font\">" +
				"			<xsl:value-of select=\"$font\" />" +
				"		</xsl:attribute></xsl:if>" +
				"	</xsl:if>" +
				"</xsl:if>" +
				"<xsl:choose>" +
				"	<xsl:when test=\"$IsRestricted\">" +
				"		<xsl:attribute name=\"textColor\">" +
				"			<xsl:value-of select=\"'#FF0000'\"/>" +
				"		</xsl:attribute>" +
				"		<xsl:value-of select=\"'" + self.preserveTags(self.getResource("", "common.restricted_property_warning")) + "'\" />" +
				"	</xsl:when>" +
				"	<xsl:otherwise>");

			switch (dataType) {
				case "item":
					var itemNameProperty = (dataSourceName == "File") ? "filename" : "id/@keyed_name";

					resXSLTArr.push(
						"<xsl:choose>" +
						"	<xsl:when test=\"" + xpath + "!='' and not(" + xpath + "/Item)\">" +
						"		<xsl:choose>" +
						"			<xsl:when test=\"" + xpath + "/@keyed_name\">" +
						"				<xsl:value-of select=\"" + xpath + "/@keyed_name\" />" +
						"			</xsl:when>" +
						"			<xsl:otherwise>" +
						"				<xsl:value-of select=\"" + xpath + "\" />" +
						"			</xsl:otherwise>" +
						"		</xsl:choose>" +
						"	</xsl:when>" +
						"	<xsl:when test=\"" + xpath + "/Item\">" +
						"		<xsl:choose>" +
						"			<xsl:when test=\"" + xpath + "/Item/@keyed_name\">" +
						"				<xsl:value-of select=\"" + xpath + "/Item/@keyed_name\" />" +
						"			</xsl:when>" +
						"			<xsl:otherwise>" +
						"				<xsl:value-of select=\"" + xpath + "/Item/" + itemNameProperty + "\" />" +
						"			</xsl:otherwise>" +
						"		</xsl:choose>" +
						"	</xsl:when>" +
						"</xsl:choose>");
					break;
				case "image":
					resXSLTArr.push("<xsl:value-of select=\"concat('&lt;img src=&quot;', string(" + xpath + "),'&quot;/&gt;')\"/>");
					break;
				case "boolean":
					resXSLTArr.push(
						"&lt;checkbox state=\"" +
						"<xsl:choose>" +
						"	<xsl:when test=\"" + xpath + "\">" +
						"		<xsl:value-of select=\"" + xpath + "\"/>" +
						"	</xsl:when>" +
						"	<xsl:otherwise>" +
						"		<xsl:value-of select=\"'0'\"/>" +
						"	</xsl:otherwise>" +
						"</xsl:choose>" +
						"\"/&gt;");
					break;
				case "md5":
					resXSLTArr.push("***");
					break;
				default:
					if ("color" != dataType) {
						resXSLTArr.push("<xsl:value-of select=\"" + xpath + "\" />");
					}
					break;
			}

			resXSLTArr.push(
				"</xsl:otherwise>" +
				"</xsl:choose>" +
				"</td>\n");
		}
	}

	var special_td_attributes = RelatedProps_Arr ? " bgColor='#f3f3f3'" : "";
	GenerateRows(DescByProps_Arr, "", special_td_attributes, "item-CSS");
	GenerateRows(RelatedProps_Arr, "related_id/Item/", "", "rItem-CSS");
	// ==== end of grid rows ===

	resXSLTArr.push("</tr>\n");
	resXSLTArr.push("</xsl:template>\n");
	resXSLTArr.push("</xsl:stylesheet>");

	return resXSLTArr.join("");
};

/*
* uiItemTypeSelectionDialog
*
* parameters:
* 1) itemTypesList - an array of objects like [{id:5, name:'Type5'}]
*/
Aras.prototype.uiItemTypeSelectionDialog = function Aras_uiItemTypeSelectionDialog(itemTypesList, wnd, callback) {
	if (!itemTypesList) return;
	wnd = wnd || window;
	var args = {
		title: this.getResource("", "itemtypeselectiondialog.select_item_type"),
		itemTypesList: itemTypesList,
		aras: this
	};
	var options = { dialogWidth: 400, dialogHeight: 280 };

	var win = this.getMostTopWindowWithAras(wnd);

	if (window.showModalDialog && !callback) {
		return this.modalDialogHelper.show("DefaultModal", win.main || win, args, options, "ItemTypeSelectionDialog.html");
	} else {
		args.dialogWidth = 400;
		args.dialogHeight = 280;
		args.content = "ItemTypeSelectionDialog.html";
		if (callback) {
			(win.main || win).ArasModules.Dialog.show("iframe", args).promise.then(callback);
		} else {
			return (win.main || win).ArasModules.Dialog.show("iframe", args).promise;
		}
	}
};

Aras.prototype.uiItemCanBeLockedByUser = function Aras_uiItemCanBeLockedByUser(itemNd, isRelationship, useSrcAccess) {
	/*
	this function is for internal use *** only ***.
	----------------------------------------------
	isRelationship - perhaps, this parameter will be removed in future
	------------------------------------------
	full list of places where function is used:
	item_window.js: updateMenuState
	itemsGrid.html: setMenuState
	relationshipsGrid.html: updateControls, onMenuCreate
	*/
	if (itemNd) {
		if (this.getItemProperty(itemNd, "is_current") == "0") {
			return false;
		}

		var itemTypeName = itemNd.getAttribute("type");

		if (itemTypeName != "File" && !this.isTempEx(itemNd)) {
			var lockedByValue = this.getItemProperty(itemNd, "locked_by_id"),
				IsMainItemLocked = true;

			if (isRelationship && useSrcAccess) {
				var sourceId = this.getItemProperty(itemNd, "source_id"),
					sourceItem, sourceItemTypeName;

				if (sourceId) {
					sourceItem = itemNd.selectSingleNode("parent::Relationships/parent::Item[@id='" + sourceId + "']");

					if (!sourceItem) {
						sourceItemTypeName = this.getItemPropertyAttribute(itemNd, "source_id", "type");
						sourceItem = this.getItemById(sourceItemTypeName, sourceId, 0);
					}
				}
				else {
					sourceItem = itemNd.selectSingleNode("parent::Relationships/parent::Item");
				}

				IsMainItemLocked = sourceItem ? this.isLockedByUser(sourceItem) : false;
			}

			return (IsMainItemLocked && lockedByValue === "");
		}
	}

	return false;
};

Aras.prototype.getItemsOfFileProperties = function Aras_getItemsOfFileProperties(itemNode, ItemTypeNode, eachFileCallback) {
	var filePropNodes = this.getPropertiesOfTypeFile(ItemTypeNode),
		filePropNodesCount = filePropNodes.length,
		files = [],
		propName,
		prop,
		file,
		i;

	for (i = 0; i < filePropNodesCount; i++) {
		propName = this.getItemProperty(filePropNodes[i], "name");
		prop = null;
		file = null;
		if ("id" === propName) {
			file = itemNode;
		}
		if (!file) {
			file = itemNode.selectSingleNode(propName + "/Item");
		}
		if (!file) {
			prop = this.getItemProperty(itemNode, propName);
			if (prop) {
				if (eachFileCallback) {
					eachFileCallback(prop);
					continue;
				}
				file = this.getItemById('File', prop, 0);
			}
		}

		if (file) {
			files.push(file);
		}
	}

	return files;
};

Aras.prototype.uiIsCheckOutPossible = function Aras_uiIsCheckOutPossible(fileItems, ItemCanBeLockedByUser, ItemIsLockedByUser) {
	/*
	this function is for internal use *** only ***.
	----------------------------------------------
	------------------------------------------
	full list of places where function is used:
	item_window.js: updateMenuState
	itemsGrid.html: setMenuState
	relationshipsGrid.html: updateControls, onMenuCreate
	*/
	if (!(ItemCanBeLockedByUser || ItemIsLockedByUser) || !fileItems) return false;
	var ThereAreFiles = false;
	for (var i = 0; i < fileItems.length; i++) {
		var file = fileItems[i];
		if (file) {
			ThereAreFiles = true;
			var FileIsLocked = this.isLocked(file);
			var FileIsTemp = this.isTempEx(file);
			if (FileIsLocked || FileIsTemp)
				return false;
		}
	}
	return ThereAreFiles; //because all rules are checked inside loop above
};

Aras.prototype.uiIsCopyFilePossible = function Aras_uiIsCopyFilePossible(fileItems) {
	/*
	this function is for internal use *** only ***.
	----------------------------------------------
	*/
	var ThereAreFiles = false;
	for (var i = 0; i < fileItems.length; i++) {
		var file = fileItems[i];
		if (file && !this.isTempEx(file)) {
			ThereAreFiles = true;
		}
	}
	return ThereAreFiles; //because all rules are checked inside loop above
};

Aras.prototype.uiWriteObject = function Aras_uiWriteObject(doc, objectHTML) {
	doc.write(objectHTML);
};

// method is obsolete, it should be deleted in the major version
Aras.prototype.uiAddConfigLink2Doc4Assembly = function Aras_uiAddConfigLink2Doc4Assembly() {
	return true;
};

Aras.prototype.uiGetFilteredObject4Grid = function Aras_uiGetFilteredObject4Grid(itemTypeID, filteredPropName, filterValue) {
	var resObj = this.newObject();
	resObj.hasError = false;

	var itemTypeNd;
	try {
		itemTypeNd = this.getItemTypeDictionary(this.getItemTypeName(itemTypeID)).node;
	} catch (ex) { }
	if (!itemTypeNd) {
		resObj.hasError = true;
		return resObj;
	}
	var fListNd = itemTypeNd.selectSingleNode("Relationships/Item[@type='Property' and name='" + filteredPropName + "']/data_source");
	var fListId = (fListNd) ? fListNd.text : null;
	if (!fListId) {
		resObj.hasError = true;
		return resObj;
	}

	var _listVals = [""];
	var _listLabels = [""];

	var optionNds = this.getListFilterValues(fListId);
	if (filterValue !== "") optionNds = this.uiGetFilteredListEx(optionNds, "^" + filterValue + "$");

	for (var i = 0, L = optionNds.length; i < L; i++) {
		var optionNd = optionNds[i];
		var label = this.getItemProperty(optionNd, "label");
		var value = this.getItemProperty(optionNd, "value");
		_listVals.push(value);
		if (label === "")
			_listLabels.push(value);
		else _listLabels.push(label);
	}

	resObj.values = _listVals;
	resObj.labels = _listLabels;

	return resObj;
};

/**
 * Case insensitive check whether exists such keyed_name in the ItemType.
 * Checks if there is an instance of the specified type with a specified keyed name in the DB.
 * The check is case insensitive if the DB was setup properly.
 * If instance cannot be defined uniquely - the first matched is used.
 * If instance doesn't exists in DB then boolean false is returned.
 * @param {string} itemTypeName - the ItemType name
 * @param {string} keyed_name - the keyed name
 * @param {boolean} skipDialog - skip showing the dialog (default value undefined (false))
 * @returns {boolean|Object}
 */
Aras.prototype.uiGetItemByKeyedName = function Aras_uiGetItemByKeyedName(itemTypeName, keyed_name, skipDialog) {
	function createCacheKey(arasObj, keyed_name) {
		return arasObj.CreateCacheKey("uiGetItemByKeyedName", itemTypeName, keyed_name);
	}

	var key = createCacheKey(this, keyed_name);
	var res = this.MetadataCache.GetItem(key);
	if (!res) {
		var q = this.newIOMItem(itemTypeName, "get");
		q.setAttribute("select", "keyed_name");
		q.setProperty("keyed_name", keyed_name);
		var r = q.apply();
		if (r.isError()) {
			return false;
		}

		var putInCache = false;
		if (r.isCollection()) {
			var candidates = [];
			for (var i = 0, L = r.getItemCount(); i < L; i++) {
				var candidate = r.getItemByIndex(i);
				if (candidate.getProperty("keyed_name") === keyed_name) //do case sensitive check
				{
					candidates.push(candidate);
				}
			}

			if (1 === candidates.length) {
				r = candidates[0];
				putInCache = true;
			}
			else {
				if (candidates.length > 1) {
					r = candidates[0];
				}
				else {
					r = r.getItemByIndex(0);
				}

				if (!skipDialog) {
					var param = {
						buttons: {btnOK: "OK"},
						defaultButton: "btnOK",
						message: this.getResource("", "ui_methods.item_cannot_defined_uniquely"),
						aras: this,
						dialogWidth: 300,
						dialogHeight: 150,
						center: true,
						content: "groupChgsDialog.html"
					};
					var win = this.getMostTopWindowWithAras(window);
					(win.main || win).ArasModules.Dialog.show("iframe", param);
				}
			}
		}
		else {
			putInCache = true;
		}

		res = r.node;
		if (putInCache) {
			this.MetadataCache.SetItem(key, res);

			var actual_keyed_name = r.getProperty("keyed_name");
			if (actual_keyed_name !== keyed_name)//this is possible in a case when the DB is case-insensitive
			{//cache mapping to correct keyed name also.
				var newKey = createCacheKey(this, actual_keyed_name);
				if (!this.MetadataCache.GetItem(newKey)) {
					this.MetadataCache.SetItem(newKey, res.cloneNode(true));
				}
			}
		}
	}

	res = res.cloneNode(true);
	return res;
};

// Retrieves window body size, the width and the height of the object including padding,
// but not including margin, border, or scroll bar.
Aras.prototype.getDocumentBodySize = function Aras_GetDocumentBodySize(document) {
	var res = this.newObject();
	res.width = 0;
	res.height = 0;

	if (document) {
		res.width = document.body.clientWidth;
		res.height = document.body.clientHeight;
	}
	return res;
};

// Retrieves the width of the rectangle that bounds the text in the text field.
Aras.prototype.getFieldTextWidth = function Aras_getFieldTextWidth(field) {
	if (field) {
		var r = field.createTextRange();
		if (r !== null)
			return r.boundingWidth;
	}
	else
		return 0;
};

// Calculate html element coordinates on a parent window.
Aras.prototype.uiGetElementCoordinates = function Aras_uiGetElementCoordinates(oNode) {
	var oCurrentNode = oNode;
	var iLeft = 0;
	var iTop = 0;
	var iScrollLeft = 0;
	var iScrollTop = 0;
	var topWindow = this.getMostTopWindowWithAras(window);
	var topOfWindow = topWindow.screenY || topWindow.screenTop || 0;
	var leftOfWindow = topWindow.screenX || topWindow.screenLeft || 0;
	var titleHeight = window.outerHeight - window.innerHeight; // calculate height of titlebar + menubar + navigation toolbar + bookmarks toolbar + tab bar; http://www.gtalbot.org/BugzillaSection/Bug195867GDR_WindowOpen.html#OuterHeightVersusHeightOrInnerHeight

	while (oCurrentNode) {
		iLeft += oCurrentNode.offsetLeft;
		iTop += oCurrentNode.offsetTop;
		iScrollLeft += oCurrentNode.scrollLeft;
		iScrollTop += oCurrentNode.scrollTop;
		if (!oCurrentNode.offsetParent) {
			var tmpFrame = null;
			try {
				oCurrentNode = oCurrentNode.ownerDocument.defaultView ? oCurrentNode.ownerDocument.defaultView.frameElement : null;
			} catch (ex) {
				//access denied case
				oCurrentNode = null;
			}
		} else {
			oCurrentNode = oCurrentNode.offsetParent;
		}
	}

	//+++ IR-008672 (Date dialog is shown not near date field after scrolling)
	var readScroll;
	if (oNode.ownerDocument.compatMode && oNode.ownerDocument.compatMode === 'CSS1Compat') readScroll = oNode.ownerDocument.documentElement;
	else readScroll = oNode.ownerDocument.body;

	iScrollLeft += readScroll.scrollLeft;
	iScrollTop += readScroll.scrollTop;

	res = {};
	res.left = iLeft - (iScrollLeft - leftOfWindow);
	res.top = iTop - (iScrollTop - topOfWindow) + titleHeight; // add height of browser bars.
	res.scrollLeft = iScrollLeft;
	res.scrollTop = iScrollTop;
	res.screenLeft = leftOfWindow;
	res.screenTop = topOfWindow;
	res.barsHeight = titleHeight;
	//--- IR-008672 (Date dialog is shown not near date field after scrolling)

	return res;
};

// Calculate coordinates of window, that would be shown near element
Aras.prototype.uiGetRectangleToShowWindowNearElement = function Aras_uiGetRectangleToShowWindowNearElement(element, windowSize, rectangleInsideElement, eventObject, isGrid) {
	if (!element) {
		throw new Error(1, this.getResource("", "ui_methods.parameter_element_not_specified"));
	}

	var parentCoords = this.uiGetElementCoordinates(element);
	var dTop, dLeft, dHeight, dWidth;
	var boundHeight;

	var hackForAddProjectDialog = false;
	if (element.name === "date_start_target" || element.name === "date_due_target") {
		var isAddProjectForm = element.ownerDocument && element.ownerDocument.formID === "1CF50C86BD1141A9863451B7634B2F04";
		if (isAddProjectForm && element.ownerDocument.defaultView) {
			hackForAddProjectDialog = true;
		}
	}

	if (eventObject && !window.viewMode && !hackForAddProjectDialog) // for dialog windows
	{
		var topY = (eventObject.screenY - eventObject.clientY) || 0;
		var leftX = (eventObject.screenX - eventObject.clientX) || 0;
		dTop = topY + parentCoords.top - parentCoords.screenTop - parentCoords.barsHeight;
		dLeft = leftX + parentCoords.left - parentCoords.screenLeft;
	}
	else {
		var keyToAvoidExplicitTopUsage = "top";
		dTop = parentCoords[keyToAvoidExplicitTopUsage];
		dLeft = parentCoords.left;
	}

	if (rectangleInsideElement) {
		dTop += rectangleInsideElement.y;
		if (!isGrid) {
			dTop += rectangleInsideElement.height;
			dLeft += rectangleInsideElement.x;
		}
		boundHeight = rectangleInsideElement.height;
	}
	else if (element.offsetHeight !== undefined) {
		if (!hackForAddProjectDialog) {
			dTop += element.offsetHeight;
		}
		boundHeight = element.offsetHeight;
	}

	if (windowSize) {
		dHeight = windowSize.height !== undefined ? windowSize.height : 200;
		dWidth = windowSize.width !== undefined ? windowSize.width : 250;

		var dx = screen.availWidth - (dLeft + dWidth);
		var dy = screen.availHeight - (dTop + dHeight);
		if (dx < 0) dLeft += dx;
		if (dy < 0) dTop -= (dHeight + boundHeight + parentCoords.barsHeight);
	}

	return { top: dTop,
		left: dLeft,
		width: dWidth,
		height: dHeight
	};
};

///<summary>
/// Show modal dialog from the specified URL using the specified dialog parameters, options
/// from "param" near element "child" of "parent" element
///</summary>
Aras.prototype.uiShowDialogNearElement = function Aras_uiShowDialogNearElement(element, dialogUrl, dialogParameters, dialogOptions, dialogSize, rectangleInsideElement, eventObject, isGrid) {
	if (!element) throw new Error(1, this.getResource("", "ui_methods.parameter_element_not_specified"));
	if (dialogOptions === undefined) dialogOptions = "status:0; help:0; center:no;";
	if (dialogSize === undefined) {
		dialogSize = { width: 250, height: 200 };
		if (dialogUrl && dialogUrl.toLowerCase().indexOf("datedialog.html") > -1)
			dialogSize = { width: 257, height: 270 };
	}

	var wndRect = this.uiGetRectangleToShowWindowNearElement(element, dialogSize, rectangleInsideElement, eventObject, isGrid);
	var dialogPositionOptions =
		"dialogHeight:" + wndRect.height +
		"px; dialogWidth:" + wndRect.width +
		"px; dialogTop:" + wndRect.top +
		"px; dialogLeft:" + wndRect.left +
		"px; ";

	dialogOptions = dialogPositionOptions + dialogOptions;

	var wnd = window;
	if (element.ownerDocument && element.ownerDocument.defaultView) {
		wnd = element.ownerDocument.defaultView;
	}

	var res = wnd.showModalDialog(dialogUrl, dialogParameters, dialogOptions);
	return res;
};

Aras.prototype.uiShowControlsApiReferenceCommand = function Aras_uiShowControlsApiReferenceCommand(isJavaScript) {
	var topHelpUrl = this.getTopHelpUrl();
	var re = /^(.*)[\\\/]([^\\\/]*)$/; //finds the last '\' or '/'
	if (!topHelpUrl || !re.test(topHelpUrl)) {
		this.AlertError(this.getResource("", "ui_methods.cannot_determine_tophelpurl"));
		return;
	}

	topHelpUrl = RegExp.$1;

	var apiReferenceFolder = isJavaScript ? "APIReferenceJavaScript" : "APIReferenceDotNet";
	window.open(topHelpUrl + "/" + apiReferenceFolder + "/Html/Index.html");
};

Aras.prototype.getNotifyByContext = function(wnd) {
	wnd = wnd || window;
	const mainWnd = this.getMainWindow();
	const topWnd = this.getMostTopWindowWithAras(wnd);
	const context = (wnd === mainWnd || topWnd.frameElement) ? mainWnd : topWnd;
	return context.ArasModules.notify;
};

Aras.prototype.getItemTypeColor = function(criteriaValue, criteriaName) {
	const colorXpath = 'Relationships/Item[@type="ITPresentationConfiguration" and client="js"]/related_id/Item/color';
	const itemTypeNode = this.getItemTypeNodeForClient(criteriaValue, criteriaName);
	const itemTypeColor = this.getValueByXPath(colorXpath, itemTypeNode);

	if (itemTypeColor) {
		return itemTypeColor;
	}

	const defaultColor = '#5C6BC0';
	const relationshipColor = '#42A5F5';
	return this.getItemProperty(itemTypeNode, 'is_relationship') === '1' ? relationshipColor : defaultColor;
};

/** ui_methodsEx.js **/
// (c) Copyright by Aras Corporation, 2004-2013.
Aras.prototype.uiRegWindowEx = function ArasUiRegWindowEx(itemID, win) {
	/*-- uiRegWindowEx
	*
	*  registers window as Innovator window.
	*  All Innovator windows get events notifications.
	*  All Innovator windows are closed when main window is closed.
	*
	*/

	if (!itemID || !win) {
		return false;
	}

	var winName = this.mainWindowName + "_" + itemID;
	this.windowsByName[winName] = win;

	return true;
};

Aras.prototype.uiUnregWindowEx = function ArasUiUnregWindowEx(itemID) {
	/*-- uiUnregWindowEx
	*
	*  unregisters window as Innovator window (should be called when item window is closed).
	*  All Innovator windows get events notifications.
	*  All Innovator windows are closed when main window is closed.
	*
	*/

	if (!itemID) {
		return false;
	}

	var winName = this.mainWindowName + "_" + itemID;
	this.deletePropertyFromObject(this.windowsByName, winName);

	return true;
};

Aras.prototype.uiFindWindowEx = function ArasUiFindWindowEx(itemID) {
	/*-- uiUnregWindowEx
	*
	*  finds registered Innovator window.
	*
	*/

	if (!itemID) {
		return null;
	}

	var winName = this.mainWindowName + "_" + itemID;
	var res = null;
	try {
		res = this.windowsByName[winName];
		if (res === undefined) {
			res = null;
		}
	} catch (excep) {
	}

	if (res && this.isWindowClosed(res)) {
		this.uiUnregWindowEx(itemID);
		return null;
	}

	return res;
};

Aras.prototype.uiFindWindowEx2 = function (itemNd) {
	var itemID = itemNd.getAttribute("id");
	var win = this.uiFindWindowEx(itemID);
	if (!win) {
		try {
			var parentItemNd = itemNd.selectSingleNode("../../../..");
			if (parentItemNd && parentItemNd.nodeType != 9) {
				var pid = parentItemNd.getAttribute("id");
				win = this.uiFindWindowEx(pid);
			}
		} catch (exc1) {
		}
	}
	if (!win) {
		win = window;
	}
	return win;
};

Aras.prototype.uiOpenWindowEx = function ArasUiOpenWindowEx(itemID, params, alertErrorWin) {
	if (!itemID) {
		return null;
	}
	if (params === undefined) {
		params = "";
	}

	var topWindow = this.getMostTopWindowWithAras(window);
	var isMainWindow = (topWindow.name === this.mainWindowName);
	var mainArasObject = this.getMainArasObject();
	var isMainArasObject = (this === mainArasObject);
	if (!topWindow.opener && !isMainArasObject) {
		return mainArasObject.uiOpenWindowEx(itemID, params);
	}

	if (!isMainWindow && topWindow.opener && !this.isWindowClosed(topWindow.opener)) {
		var wnd = topWindow.opener.aras.uiOpenWindowEx(itemID, params, this.getCurrentWindow());
		if (!wnd.opener && topWindow.opener) {
			wnd.opener = topWindow.opener;
		}

		return wnd;
	} else {
		var winName = this.mainWindowName + "_" + itemID;
		var win = null;
		if (this.browserHelper.newWindowCanBeOpened(this)) {
			this.browserHelper.lockNewWindowOpen(this, true);
			try {
				if (params.indexOf("isOpenInTearOff=true") > -1) {
					win = topWindow.open(this.getScriptsURL() + "../scripts/blank.html", winName, params);
				} else {
					var isUnfocused = params.indexOf("isUnfocused=true") > -1;
					win = arasTabs.open(this.getScriptsURL() + "../scripts/blank.html", winName, isUnfocused);
				}
			} finally {
				this.browserHelper.lockNewWindowOpen(this, false);
			}

			if (!win) {
				this.AlertError(this.getResource("", "ui_methods_ex.innovator_failed_to_open_new_window"), alertErrorWin, "");
			}
		} else {
			this.AlertSuccess(this.getResource("", "ui_methods_ex.another_window_opening_is_in_progress"));
			return false;
		}

		if (win) {
			try {//substitute opener for the new window
				if (topWindow.opener && !this.isWindowClosed(topWindow.opener) && topWindow.opener.name == this.mainWindowName) {
					//according to CVS commits this is fix for IR-001690 "Toolbar does not load" (read background).
					//Something to workaround google popup blocker.
					win.opener = topWindow.opener;
				}
			} catch (excep) { /* security exception may occur */ }
		}

		return win;
	}
};

Aras.prototype.uiCloseWindowEx = function (itemID) {
	if (!itemID) {
		return false;
	}

	var win = this.uiFindWindowEx(itemID);
	if (win) {
		win.close();
	}

	return true;
};

/*
* uiGetFormID4ItemEx - function to get id of form correspondent to the item (itemNd) and mode
*                  (result depends on current user)
*
* parameters:
* itemNd   - xml node of item to find correspondent form
* formType - string, representing mode: 'add', 'view', 'edit' or 'print'
*/
Aras.prototype.uiGetFormID4ItemEx = function ArasUiGetFormID4ItemEx(itemNd, formType) {
	function findMaxPriorityFormID(itemType, roles, formType) {
		var i;
		var arasObj = self;
		var returnNodes;

		var tryGetClassificationFormWithoutFormType = function () {
			xp = "Relationships/Item[@type='View' and not(type='complete') and not(type='preview') and " + strRoles + "][not(form_classification[@is_null='1'])]/related_id/Item[@type='Form']";
			return itemType.selectNodes(xp);
		};

		if (typeof (roles) == "string") {
			var tmpRoles = roles;
			roles = [];
			roles.push(tmpRoles);
		}
		var strRoles = "(role='" + roles.join("' or role='") + "')";

		if (classification) {
			var xp = "Relationships/Item[@type='View' and " + strRoles + " and type='" + formType + "'][not(form_classification[@is_null='1'])]/related_id/Item[@type='Form']";
			var formIds = [];
			var nodes = itemType.selectNodes(xp);
			var tmpNds = nodes.length > 0 ? nodes : tryGetClassificationFormWithoutFormType();
			if (tmpNds.length > 0) {
				for (i = 0; i < tmpNds.length; i++) {
					var formClassification = tmpNds[i].parentNode.parentNode.selectSingleNode("form_classification").text;
					if (arasObj.areClassPathsEqual(formClassification, classification)) {
						formIds.push(tmpNds[i].getAttribute("id"));
					}
				}
			} else {
				returnNodes = null;
			}

			if (formIds.length > 0) {
				var additionalXp = "[@id='" + formIds.join("' or @id='") + "']";
				xp += additionalXp;
				returnNodes = itemType.selectNodes(xp);
			}
		}
		if (!(returnNodes && (returnNodes.length !== 0))) {
			returnNodes = itemType.selectNodes("Relationships/Item[@type='View' and string(form_classification)='' and " + strRoles + " and type='" + formType + "']/related_id/Item[@type='Form']");
		}

		var formNds = returnNodes;
		if (formNds.length === 0) {
			return "";
		}

		var currForm = formNds[0];
		var currPriority = arasObj.getItemProperty(formNds[0].selectSingleNode("../.."), "display_priority");
		if (currPriority === "") {
			currPriority = Number.POSITIVE_INFINITY;
		}

		for (i = 1; i < formNds.length; i++) {
			var priority = arasObj.getItemProperty(formNds[i].selectSingleNode("../.."), "display_priority");
			if (priority === "") {
				priority = Number.POSITIVE_INFINITY;
			}

			if (currPriority > priority) {
				currPriority = priority;
				currForm = formNds[i];
			}
		}

		return currForm.getAttribute("id");
	}

	function findMaxPriorityFormIDForItemType(anItemType, formType) {
		var array = [identityId, userIdentities, worldIdentityId];
		for (var i = 0; i < array.length; i++) {
			var identity = array[i];
			var res = findMaxPriorityFormID(anItemType, identity, formType);
			if (res) {
				return res;
			}

			if (formType !== "default" && formType !== "complete") {
				res = findMaxPriorityFormID(anItemType, identity, "default");
				if (res) {
					return res;
				}
			}
		}

		return undefined;
	}

	if (!itemNd) {
		return "";
	}
	if (!formType || formType.search(/^default$|^add$|^view$|^edit$|^print|^preview$|^search|^complete$/) == -1) {
		return "";
	}

	var worldIdentityId = 'A73B655731924CD0B027E4F4D5FCC0A9';
	var userIdentities = this.getIdentityList().split(",");
	if (userIdentities.length === 0) {
		return "";
	} else {
		var index = userIdentities.indexOf(worldIdentityId);
		if (index > -1) {
			userIdentities.splice(index, 1);
		}
	}

	var userNd = null;
	var tmpUserID = this.getCurrentUserID();

	if (tmpUserID == this.getUserID()) {
		userNd = this.getLoggedUserItem();
	} else {
		userNd = this.getItemFromServerWithRels("User", tmpUserID, "id", "Alias", "related_id(id)", true).node;
	}
	if (!userNd) {
		return "";
	}

	var identityNd = userNd.selectSingleNode("Relationships/Item[@type='Alias']/related_id/Item[@type='Identity']");
	if (!identityNd) {
		return "";
	}

	var identityId = identityNd.getAttribute("id");
	var itemTypeName = itemNd.getAttribute("type");
	var itemTypeNd = this.getItemTypeNodeForClient(itemTypeName, "name");
	var classification;
	var classificationNode = itemNd.selectSingleNode("classification");
	if (classificationNode) {
		classification = classificationNode.text;
	}

	var self = this;

	var formID = findMaxPriorityFormIDForItemType(itemTypeNd, formType);
	if (!formID && this.getItemProperty(itemTypeNd, "implementation_type") == "polymorphic") {
		var itemtypeId = this.getItemProperty(itemNd, "itemtype");
		if (itemtypeId) {
			itemTypeNd = this.getItemTypeNodeForClient(itemtypeId, "id");
			if (itemTypeNd) {
				formID = findMaxPriorityFormIDForItemType(itemTypeNd, formType);
			}
		}
	}

	return formID;
};

/*
* uiGetRelationshipView4ItemTypeEx - function to get Relationship View of ItemType
*                  (result depends on current user)
*
* parameters:
* itemType   - xml node of ItemType
*/
Aras.prototype.uiGetRelationshipView4ItemTypeEx = function ArasUiGetRelationshipView4ItemTypeEx(itemType) {
	if (!itemType) {
		return null;
	}

	var userIdentities = this.getIdentityList().split(",");
	if (userIdentities.length === 0) {
		return null;
	}

	var userNd = null;
	var tmpUserID = this.getCurrentUserID();

	if (tmpUserID == this.getUserID()) {
		userNd = this.getLoggedUserItem();
	} else {
		userNd = this.getItemFromServerWithRels("User", tmpUserID, "id", "Alias", "related_id(id)", true).node;
	}
	if (!userNd) {
		return null;
	}

	var identityNd = userNd.selectSingleNode("Relationships/Item[@type='Alias']/related_id/Item[@type='Identity']");
	if (!identityNd) {
		return null;
	}

	var identityId = identityNd.getAttribute("id");

	var res = itemType.selectSingleNode("Relationships/Item[@type='Relationship View' and (related_id/Item/@id='" + identityId + "' or related_id='" + identityId + "')]");
	if (!res) {
		for (var i = 0; i < userIdentities.length; i++) {
			res = itemType.selectSingleNode("Relationships/Item[@type='Relationship View' and (related_id/Item/@id='" + userIdentities[i] + "' or related_id='" + userIdentities[i] + "')]");
			if (res) {
				break;
			}
		}
	}

	return res;
};

/*
* uiGetTOCView4ItemTypeEx - function to get TOC View of ItemType
*                  (result depends on current user)
*
* parameters:
* itemType   - xml node of ItemType
*/
Aras.prototype.uiGetTOCView4ItemTypeEx = function ArasUiGetTOCView4ItemTypeEx(itemType) {
	if (!itemType) {
		return null;
	}

	var userIdentities = this.getIdentityList().split(",");
	if (userIdentities.length === 0) {
		return null;
	}

	var userNd = null;
	var tmpUserID = this.getCurrentUserID();

	if (tmpUserID == this.getUserID()) {
		userNd = this.getLoggedUserItem();
	} else {
		userNd = this.getItemFromServerWithRels("User", tmpUserID, "id", "Alias", "related_id(id)", true).node;
	}
	if (!userNd) {
		return null;
	}

	var identityNd = userNd.selectSingleNode("Relationships/Item[@type='Alias']/related_id/Item[@type='Identity']");
	if (!identityNd) {
		return null;
	}

	var identityId = identityNd.getAttribute("id");

	var res = itemType.selectSingleNode("Relationships/Item[@type='TOC View' and (related_id/Item/@id='" + identityId + "' or related_id='" + identityId + "')]");
	if (!res) {
		for (var i = 0; i < userIdentities.length; i++) {
			res = itemType.selectSingleNode("Relationships/Item[@type='TOC View' and (related_id/Item/@id='" + userIdentities[i] + "' or related_id='" + userIdentities[i] + "')]");
			if (res) {
				break;
			}
		}
	}

	return res;
};

/*
* uiGetForm4ItemEx - function to get form xml node correspondent to the item (itemNd) and mode
*                  (result depends on current user)
*
* parameters:
* itemNd   - xml node of item to find correspondent form
* formType - string, representing mode: 'add', 'view', 'edit' or 'print'
*/
Aras.prototype.uiGetForm4ItemEx = function (itemNd, formType) {
	if (!itemNd) {
		return null;
	}
	if (!formType || formType.search(/^default$|^add$|^view$|^edit$|^preview$|^print$|^search|^complete$/) == -1) {
		return null;
	}
	var formID = this.uiGetFormID4ItemEx(itemNd, formType);
	var formNd = formID ? this.getFormForDisplay(formID).node : null;
	return formNd;
};

/*
* uiShowItemEx
*
* parameters:
* 1) itemNd          - item to be shown
* 2) viewMode        - 'tab view' or 'openFile'
* 3) isOpenInTearOff - true or false
*/
Aras.prototype.uiShowItemEx = function ArasUiShowItemEx(itemNd, viewMode, isOpenInTearOff, isUnfocused) {
	function onShowItem(inDom, inArgs) {
		var itemTypeName = inDom.getAttribute('type');
		var itemType = this.getItemTypeNodeForClient(itemTypeName);
		var onShowItemEv = itemType.selectNodes("Relationships/Item[@type='Client Event' and client_event='OnShowItem']/related_id/Item");

		try {
			if (onShowItemEv.length) {
				return this.evalMethod(this.getItemProperty(onShowItemEv[0], "name"), inDom, inArgs);
			} else {
				return this.evalMethod("OnShowItemDefault", inDom, inArgs);
			}
		} catch (exp) {
			this.AlertError(this.getResource("", "item_methods.event_handler_failed"),
				this.getResource("", "item_methods.event_handler_failed_with_message", exp.description),
				this.getResource("", "common.client_side_err"));
			return false;
		}
	}

	if (!itemNd) {
		return false;
	}
	if (itemNd.getAttribute("discover_only") === "1") {
		this.AlertError(this.getResource("", "ui_methods_ex.discover_only_item_cannot_be_opened"), "", "");
		return false;
	}
	const itemTypeName = itemNd.getAttribute("type");
	viewMode = viewMode || "tab view";
	let asyncResult = onShowItem.call(this, itemNd, { viewMode: viewMode, isOpenInTearOff: isOpenInTearOff, isUnfocused: isUnfocused });

	if (!asyncResult) {
		asyncResult = Promise.resolve();
	}

	return asyncResult;
};

Aras.prototype.uiOpenEmptyWindowEx = function ArasUiOpenEmptyWindowEx(itemNd) {
	var itemID = itemNd.getAttribute("id");
	var win = this.uiFindAndSetFocusWindowEx(itemID);
	if (win !== null) {
		return true;
	}

	win = this.uiOpenWindowEx(itemID, "scrollbars=no,resizable=yes,status=yes");
	if (!win) {
		return false;
	}
	this.uiRegWindowEx(itemID, win);
	return true;
};

Aras.prototype.uiFindAndSetFocusWindowEx = function ArasUiFindAndSetFocusWindowEx(itemID) {
	var win = this.uiFindWindowEx(itemID);
	if (win) {
		if (win.opener === undefined) {
			this.uiUnregWindowEx(itemID);
			win = null;
		} else {
			this.browserHelper.setFocus(win);
		}
	} else {
		win = null;
	}

	return win;
};

/*
* uiReShowItemEx
*
* parameters:
* 1) oldItemID- old id of item to be shown
* 2) itemNd   - item to be shown //usually itemId==oldItemId
* 3) viewMode - "tab view" or "openFile"
*/
Aras.prototype.uiReShowItemEx = function ArasUiReShowItemEx(oldItemID, itemNd, viewMode) {
	if (!oldItemID) {
		return false;
	}
	if (!itemNd) {
		return false;
	}
	viewMode = viewMode || "tab view";
	var win = this.uiFindWindowEx(oldItemID);
	if (!win || this.isWindowClosed(win)) {
		return this.uiShowItemEx(itemNd, viewMode);
	}

	var itemWin;
	if (win.getItem) {
		itemWin = win.getItem();
	} else {
		itemWin = win.item;
	}
	var itemID = itemNd.getAttribute("id");
	var itemTypeName = itemNd.getAttribute("type");
	if (itemTypeName == "File" && viewMode == "openFile") {
		return this.uiShowItemEx(itemNd, viewMode);
	}
	var isReloadFrm = false;
	var oldFormId = this.uiGetFormID4ItemEx(itemWin, win.isEditMode ? "edit" : "view");
	var newFormId = this.uiGetFormID4ItemEx(itemNd, win.isEditMode ? "edit" : "view");
	if (!newFormId) {
		var doc = win.frames.instance.document;
		doc.open();
		doc.write("<html><body><center>" + this.getResource("", "ui_methods_ex.form_not_specified_for_you", win.isEditMode ? "edit" : "view") + "</center></body></html>");
		doc.close();
		return;
	}
	if (oldItemID != itemID) {
		this.uiUnregWindowEx(oldItemID);
		this.uiRegWindowEx(itemID, win);

		isReloadFrm = true;
		if (newFormId != oldFormId) {
			if (win.name != "work") {
				win.close();
				isReloadFrm = false;
			}
		}
	}

	this.RefillWindow(itemNd, win, isReloadFrm);

	if (win.updateMenu) {
		win.updateMenu();
	}
};

Aras.prototype.RefillWindow = function ArasRefillWindow(itemNd, win, isReloadFrm) {
	var itemWin;
	if (win.getItem) {
		itemWin = win.getItem();
	} else {
		itemWin = win.item;
	}

	if (itemWin && "update" == itemWin.getAttribute("action") && itemWin.getAttribute("id") != itemNd.getAttribute("id")) {
		isReloadFrm = true;
	}

	var itemID = itemNd.getAttribute("id");
	var typeID = itemNd.getAttribute("typeId");
	var itemTypeName = this.getItemTypeName(typeID);
	var winName = this.mainWindowName + "_" + itemID;
	win.name = winName;
	if (win.setItem) {
		win.setItem(itemNd);
	} else {
		win.item = itemNd;
	}
	win.itemID = itemID;
	var itemTypeNd = this.getItemTypeNodeForClient(itemTypeName);
	win.itemType = itemTypeNd;
	var newIsEditMode = this.isTempEx(itemNd) || (this.isLockedByUser(itemNd) && win.isEditMode);
	win.isTearOff = true;
	win.itemTypeName = itemTypeName;
	if (win.updateRootItem) {
		if (!win.isEditModeUnchangeable) {
			win.isEditMode = newIsEditMode;
		}
		var queryString;
		if (isReloadFrm && win.relationships) {
			var openTab = win.relationships.relTabbar.GetSelectedTab();
			queryString = { db: this.getDatabase(), ITName: itemTypeName, relTypeID: openTab, itemID: itemID, editMode: (win.isEditMode ? 1 : 0), tabbar: "1", toolbar: "1", where: "tabview" };
		}
		win.updateRootItem(itemNd, queryString);
		if (win.getViewersTabs) {
			var updateSidebar = function () {
				setTimeout(function () {
					var tabsControl = win.getViewersTabs();
					var currentTabId = tabsControl.getCurrentTabId();

					var callback = function (viewerContainer) {
						const viewers = viewerContainer.getChildren();
						if (viewers.length) {
							var frame = viewers[0].viewerFrame;
							if (frame && !frame.contentWindow.SSVCViewer) {
								frame.contentWindow.onViewerIsReady = function () {
									var args = frame.contentWindow.VC.Utils.Page.GetParams();
									frame.contentWindow.SSVCViewer.displayFile(args.fileUrl);
								};
							}
						}
					};

					tabsControl.selectTab(currentTabId, callback);
					document.removeEventListener("loadSideBar", updateSidebar);
				}, 0);
			};
			document.addEventListener("loadSideBar", updateSidebar);
		}
	} else {
		this.AlertError(this.getResource("", "ui_methods_ex.function_update_root_item_not_implemented"), "", "", win);
	}
	if (win.document.getElementById("edit") && win.document.getElementById("form_frame")) {
		this.uiShowItemInFrameEx(win.getElementById("form_frame"), win.item, (win.isEditMode ? "edit" : "view"));
	}
};

Aras.prototype.uiPopulatePropertiesOnWindow = function ArasUiPopulatePropertiesOnWindow(hostWindow, itemNd, itemTypeNd, formNd, isEditMode, mode, userChangeHandler) {
	var itemID;
	var itemTypeName;

	var itemTypeID;
	var iomItem;
	var formID = formNd.getAttribute("id");

	var winParams = {};

	winParams.aras = this;
	winParams.viewMode = mode;
	winParams.isEditMode = isEditMode;

	winParams.formID = formID;
	winParams.formNd = formNd;

	//uiShowItemInFrameEx method where current method is called calculate itemTypeNd from itemNd, it is not possible to have itemNd wihtout itemTypeNd calculated
	if (itemNd && itemTypeNd) {
		itemID = itemNd.getAttribute("id");

		iomItem = this.newIOMItem();
		iomItem.dom = itemNd.ownerDocument;
		iomItem.node = itemNd;

		winParams.item = itemNd;
		winParams.itemNd = itemNd;

		winParams.thisItem = iomItem;

		//In case of SearchMode form (for example search by criteria @{0}) itemNd exist, but it is query AML which doesn't have id at all, make sure that isTemp in that case
		//set to true
		winParams.itemID = itemID;
		winParams.isTemp = this.isTempEx(itemNd);
	}

	//method uiDrawFormEx is not require to have itemNd populated, for example on Form editor. But itemTypeNd in this case should be populated (it will be used to populate list on forms fields)
	if (itemTypeNd) {
		itemTypeID = itemTypeNd.getAttribute("id");
		itemTypeName = this.getItemProperty(itemTypeNd, "name");

		winParams.itemTypeID = itemTypeID;
		winParams.itemType = itemTypeNd;
		winParams.itemTypeNd = itemTypeNd;
		winParams.itemTypeName = itemTypeName;
	}

	if (userChangeHandler) {
		winParams.userChangeHandler = userChangeHandler;
	}

	//it is assuming that there is no racing conditions for two or more forms opened in the same time. First form will be loaded, then second form will erase windowArgumentsExchange and setup it again.
	//In case of error it will be required to fix more than just creating something like hostWindow._<%form_id%>_params,
	//because it can be situation when two items with the same form is opened simulteneously from the same origin window.
	//It will be required to pass some guid to the window, but it is not allowed to add it to query string, due to cache issues.
	//It will be requried to use window.name property which is set up as <iframe name> or window.open('url', name)
	hostWindow.eval("window.windowArgumentsExchange = window.windowArgumentsExchange || {};");
	hostWindow.windowArgumentsExchange["_" + formID + "_params"] = winParams;
};

/*
* uiShowItemInFrameEx
* frame
* itemNd
* formType - 'add', 'view', 'edit', 'default', 'edit_form' (also this parameter defines mode to open item)
* formNd4Display - if specified then this form is used to display the item
*/
Aras.prototype.uiShowItemInFrameEx = function (frame, itemNd, formType, nestedLevel, formNd4Display, itemTypeNd4Form, userChangeHandler, listItems) {
	if (!frame) {
		return false;
	}
	if (!itemNd && !formNd4Display) {
		return false;
	}
	if (formType === undefined) {
		formType = "view";
	}
	if (nestedLevel === undefined) {
		nestedLevel = 0;
	}

	var itemTypeName;
	var itemTypeNd;
	var itemTypeLabel;

	if (itemTypeNd4Form) {
		itemTypeNd = itemTypeNd4Form;
		itemTypeName = this.getItemProperty(itemTypeNd4Form, "name");
	} else if (itemNd) {
		itemTypeName = itemNd.getAttribute("type");
		itemTypeNd = this.getItemTypeNodeForClient(itemTypeName);
	}

	if (itemTypeNd) {
		itemTypeLabel = this.getItemProperty(itemTypeNd, "label");
		if (!itemTypeLabel) {
			itemTypeLabel = itemTypeName;
		}
	}

	var isEditMode = (formType == "edit" || formType == "search" || formType == "add" || formType == "edit_form");

	//in IE document.frameid returns a window which is passed into method, it has all required proeprties, such as .parent
	//in FF document.frameid returns a dom element, which doesn't have .parent property it is contained on frame.contentWindow
	//current method is called with two possible cases when dom element is passed or when window object is passed
	if (frame.contentWindow) {
		frame = frame.contentWindow;
	}

	frame.parent.nestedLevel = nestedLevel;

	var formNd = formNd4Display ? formNd4Display : this.uiGetForm4ItemEx(itemNd, (formType != "edit_form" ? formType : "edit"));
	if (!formNd) {
		frame.document.open();
		frame.document.write("<html><body><center>" + this.getResource("", "ui_methods_ex.form_not_specified_for_you", formType) + "</center></body></html>");
		frame.document.close();
		try {
			if (frame.parent.updateMenuState) {
				frame.parent.updateMenuState();
			}
		} catch (excep) {
		}
		return false;
	}

	if (nestedLevel <= this.maxNestedLevel) {
		this.uiPopulatePropertiesOnWindow(frame.parent, itemNd, itemTypeNd, formNd, isEditMode, formType, userChangeHandler);
		var request = this.uiDrawFormEx(formNd, formType, itemTypeNd, listItems);
		frame.location = request;

		if (itemNd) {
			var formName = this.getItemProperty(formNd, "name");
			this.saveUICommandHistoryIfNeed(itemTypeNd, itemNd, "view", formName);
		}
	} else {
		frame.document.open();
		frame.document.write(this.getResource("", "ui_methods_ex.itemtype_label_item_is_here", itemTypeLabel, this.getKeyedNameEx(itemNd)));
		frame.document.close();
	}
};

Aras.prototype._getBaseDrawingModel = function ArasGetBaseDrawingModel(formID, mode, itemTypeNd, isFormTemp, isFormLockedByUser, formLastModifiedDate, itemTypeLastModifiedDate, listItems) {
	var itemTypeId = "";
	itemTypeLastModifiedDate = itemTypeLastModifiedDate || "";

	if (itemTypeNd) {
		itemTypeNd = itemTypeNd.cloneNode(true);
	}

	var languageCode = this.getSessionContextLanguageCode();
	formLastModifiedDate = formLastModifiedDate || this.MetadataCache.ExtractDateFromCache(formID, "id", "Form");
	var database = this.getDatabase();

	if (itemTypeNd) {
		itemTypeId = itemTypeNd.getAttribute("id");
		itemTypeLastModifiedDate = itemTypeLastModifiedDate || this.MetadataCache.ExtractDateFromCache(itemTypeId, "id", "ItemType");
	}

	// List info XML generating
	var getListIds = function (isFilter) {
		var listIdNds = !itemTypeNd ? [] : itemTypeNd.selectNodes("Relationships/Item[@type='Property' and contains(string(data_type), '" + (isFilter ? "filter" : "list") + "')]/data_source");
		var listIds = [];
		for (var i = 0; i < listIdNds.length; i++) {
			if (listIdNds[i].text) {
				listIds.push(listIdNds[i].text);
			}
		}

		var foreignPropertys = !itemTypeNd ? [] : itemTypeNd.selectNodes("Relationships/Item[@type='Property' and data_type='foreign']");
		for (i = 0; i < foreignPropertys.length; i++) {
			var foreinItemType = aras.getItemTypeNodeForClient(
				foreignPropertys[i].parentNode.selectSingleNode("Item[@type='Property' and data_type = 'item' and " +
					"id = '" + foreignPropertys[i].selectSingleNode('data_source').text  + "']/data_source").text, 'id');
			var dataSourceProp = foreinItemType.selectSingleNode("Relationships/Item[@type='Property' and " +
				"contains(string(data_type), '" + (isFilter ? "filter" : "list") + "') and " +
				"id = '" + foreignPropertys[i].selectSingleNode('foreign_property').text + "']/data_source");
			if (dataSourceProp && dataSourceProp.text) {
				listIds.push(dataSourceProp.text);
			}
		}
		return listIds;
	};
	var listInfoXml;
	if (listItems) {
		listInfoXml = "<Item><Relationships>";
		for (var itemindex = 0; itemindex < listItems.getItemCount(); itemindex++) {
			listInfoXml += listItems.GetItemByIndex(itemindex).node.xml;
		}
		listInfoXml += "</Relationships></Item>";
	} else {
		var listInfo = this.MetadataCache.GetList(getListIds(false), []);
		listInfoXml = "<Item>" + listInfo.resultsXML.replace(/<(.?)Result(.?)>/g, "<$1Relationships$2>") + "</Item>";
	}

	var filterListInfo = this.MetadataCache.GetList([], getListIds(true));

	// Foreign items info XML generating
	var foreignInfo = {};
	var properties = !itemTypeNd ? [] : itemTypeNd.selectNodes("Relationships/Item[@type='Property' and data_type='foreign']");
	for (var i = 0; i < properties.length; i++) {
		foreignInfo[properties[i].getAttribute("id")] = this.uiMergeForeignPropertyWithSource(properties[i]).xml;
	}

	//Remove xPropertiesInfo
	const allowedProperties = !itemTypeNd ? [] : ArasModules.xml.selectNodes(itemTypeNd, "Relationships/Item[@type='xItemTypeAllowedProperty']");
	allowedProperties.forEach(function(xProperty) {
		xProperty.parentNode.removeChild(xProperty);
	});

	// TODO: Create server method for resource using
	var resourceInfo = {};
	resourceInfo["ui_methods_ex.clear_file_property"] = this.getResource("", "ui_methods_ex.clear_file_property");
	resourceInfo["ui_methods_ex.scan_in_file"] = this.getResource("", "ui_methods_ex.scan_in_file");
	resourceInfo["ui_methods_ex.add_file"] = this.getResource("", "ui_methods_ex.add_file");
	resourceInfo["ui_methods_ex.check_out_file"] = this.getResource("", "ui_methods_ex.check_out_file");
	resourceInfo["ui_methods_ex.check_in_file"] = this.getResource("", "ui_methods_ex.check_in_file");
	resourceInfo["ui_methods_ex.select_an_image"] = this.getResource("", "ui_methods_ex.select_an_image");
	resourceInfo["ui_methods_ex.hide_relationships_print_view"] = this.getResource("", "ui_methods_ex.hide_relationships_print_view");
	resourceInfo["common.restricted_property_warning"] = this.getResource("", "common.restricted_property_warning");
	resourceInfo["file_management.select_and_upload_file"] = this.getResource("", "file_management.select_and_upload_file");
	resourceInfo["file_management.manage_file_property"] = this.getResource("", "file_management.manage_file_property");
	resourceInfo['xClassesControl.default_label'] = this.getResource('../Modules/aras.innovator.ExtendedClassification/',
		'xClassesControl.default_label');

	// send resources for xClassesFromControl to use localization for control in form editor
	if(mode === 'edit_form' || mode === 'view_form') {
		resourceInfo['xClassesControl.edit_form.xClass_Sample_1'] = this.getResource('../Modules/aras.innovator.ExtendedClassification/',
			'xClassesControl.edit_form.xClass_Sample_1');
		resourceInfo['xClassesControl.edit_form.xClass_Sample_2'] = this.getResource('../Modules/aras.innovator.ExtendedClassification/',
			'xClassesControl.edit_form.xClass_Sample_2');
		resourceInfo['xClassesControl.edit_form.xProperty_A'] = this.getResource('../Modules/aras.innovator.ExtendedClassification/',
			'xClassesControl.edit_form.xProperty_A');
		resourceInfo['xClassesControl.edit_form.xProperty_B'] = this.getResource('../Modules/aras.innovator.ExtendedClassification/',
			'xClassesControl.edit_form.xProperty_B');
		resourceInfo['xClassesControl.edit_form.xProperty_C'] = this.getResource('../Modules/aras.innovator.ExtendedClassification/',
			'xClassesControl.edit_form.xProperty_C');
		resourceInfo['xClassesControl.edit_form.xProperty_X'] = this.getResource('../Modules/aras.innovator.ExtendedClassification/',
			'xClassesControl.edit_form.xProperty_X');
		resourceInfo['xClassesControl.edit_form.xProperty_Y'] = this.getResource('../Modules/aras.innovator.ExtendedClassification/',
			'xClassesControl.edit_form.xProperty_Y');
		resourceInfo['xClassesControl.edit_form.xProperty_Y.value'] = this.getResource('../Modules/aras.innovator.ExtendedClassification/',
			'xClassesControl.edit_form.xProperty_Y.value');
		resourceInfo['xClassesControl.edit_form.xProperty_Z'] = this.getResource('../Modules/aras.innovator.ExtendedClassification/',
			'xClassesControl.edit_form.xProperty_Z');
	}

	// Custom JS info XML generating
	var browserCode = "";
	if (this.Browser.isIe()) {
		browserCode = "ie";
	} else if (this.Browser.isEdge()) {
		browserCode = "ed";
	} else if (this.Browser.isCh()) {
		browserCode = "ch";
	} else {
		browserCode = "ff";
	}

	var jsInfo = "<js_info>" +
					"<databasehash>" + this.calcMD5(database) + "</databasehash>" +
					"<scripts_url>" + (this.getScriptsURL()) + "</scripts_url>" +
					"<formId>" + formID + "</formId>" +
					"<itemTypeId>" + itemTypeId + "</itemTypeId>" +
					"<itemTypeLastModifiedDate>" + itemTypeLastModifiedDate + "</itemTypeLastModifiedDate>" +
					"<languageCode>" + languageCode + "</languageCode>" +
					"<formLastModifiedDate>" + formLastModifiedDate + "</formLastModifiedDate>" +
					"<mode>" + mode + "</mode>" +
					"<isTemp>" + isFormTemp + "</isTemp>" +
					"<isLockedByUser>" + isFormLockedByUser + "</isLockedByUser>" +
					"<browserCode>" + browserCode + "</browserCode>" +
				"</js_info>";

	var langInfo = this.getLanguagesResultNd().xml;

	var baseModel = {
		JSInfo: jsInfo,
		ItemTypeInfo: itemTypeNd ? itemTypeNd.xml : "",
		AllLanguages: "<Item>" + langInfo.replace(/<(.?)Result(.?)>/g, "<$1Relationships$2>") + "</Item>",
		ForeignInfo: JSON.stringify(foreignInfo),
		ListInfo: listInfoXml,
		FilterListInfo: "<Item>" + filterListInfo.resultsXML.replace(/<(.?)Result(.?)>/g, "<$1Relationships$2>") + "</Item>",
		ResourceInfo: JSON.stringify(resourceInfo)
	};

	return baseModel;
};

/*
* uiDrawFormEx
* doc
* formNd
* mode - (add, edit, view, print, view_form, edit_form, search)
*/
Aras.prototype.uiDrawFormEx = function ArasUiDrawFormEx(formNd, mode, itemTypeNd, listItems) {
	if (!formNd || !mode) {
		return;
	}
	if (!itemTypeNd) {
		itemTypeNd = null;
	}

	var formID = formNd.getAttribute("id");
	var itemTypeId = "";
	var itemTypeLastModifiedDate = "";

	var languageCode = this.getSessionContextLanguageCode();
	var formLastModifiedDate = this.getItemProperty(formNd, "modified_on") || this.MetadataCache.ExtractDateFromCache(formID, "id", "Form");
	var database = this.getDatabase();

	if (itemTypeNd) {
		itemTypeId = itemTypeNd.getAttribute("id");
		itemTypeLastModifiedDate = this.getItemProperty(itemTypeNd, "modified_on") || this.MetadataCache.ExtractDateFromCache(itemTypeId, "id", "ItemType");
	}

	var request = this.getScriptsURL("virtualGetForm?");
	request += "formId=" + formID + "&formLastModifiedDate=" + formLastModifiedDate + "&languageCode=" + languageCode;
	request += "&itemTypeId=" + itemTypeId + "&itemTypeLastModifiedDate=" + itemTypeLastModifiedDate;
	request += "&databasehash=" + this.calcMD5(database) + "&mode=" + mode;

	var xmlHttp = this.XmlHttpRequestManager.CreateRequest();
	xmlHttp.open("GET", request, false);
	xmlHttp.send(null);

	// Check if form is cached in browser
	if (xmlHttp.status == 200) {
		// nothing special, browser will load the page by returned url
	} else if (xmlHttp.status == 404) {
		// If form isn't cached - we send it to server in POST
		xmlHttp = this.XmlHttpRequestManager.CreateRequest();
		xmlHttp.open("POST", this.getBaseURL() + "/Modules/aras.innovator.core.Form/PostForm", false);
		xmlHttp.setRequestHeader("Content-Type", "application/json; charset=utf-8");

		var formModel = this._getBaseDrawingModel(formID, mode, itemTypeNd, this.isTempEx(formNd), this.isLockedByUser(formNd), formLastModifiedDate, itemTypeLastModifiedDate, listItems);
		formModel.FormInfo = formNd.xml;
		formModel = JSON.stringify(formModel);
		xmlHttp.send(formModel);
	}

	return request;
};

/*
Returns string: field type 4 specified Property
*/
Aras.prototype.uiGetFieldType4Property = function ArasUiGetFieldType4Property(propertyNd) {
	var fieldtype = "text";

	if (!propertyNd) {
		return fieldtype;
	}

	var datatype = this.getItemProperty(propertyNd, "data_type");
	var propertyName = this.getItemProperty(propertyNd, "name");

	if (datatype == "string" || datatype == "integer" || datatype == "float" || datatype == "decimal" || datatype == "sequence") {
		fieldtype = "text";

		var storedLength = this.getItemProperty(propertyNd, 'stored_length');
		storedLength = parseInt(storedLength);

		if (!isNaN(storedLength) && storedLength > 64) {
			fieldtype = "textarea";
		}
	} else if (datatype == "item") {
		if (this.getItemProperty(propertyNd, "data_source") == this.getItemTypeId("File")) {
			fieldtype = "file item";
		} else {
			fieldtype = "item";
		}
	} else if (datatype == "ml_string") {
		fieldtype = "ml_string";
	} else if (datatype == "mv_list") {
		fieldtype = "listbox multi select";
	} else if (datatype == "list" || datatype == "filter list" || datatype == "color list") {
		fieldtype = "dropdown";
	} else if (datatype == "formatted text") {
		fieldtype = "formatted text";
	} else if (datatype == "boolean") {
		fieldtype = "checkbox";
	} else if (datatype == "date") {
		fieldtype = "date";
	} else if (datatype == "md5") {
		fieldtype = "password";
	} else if (datatype == "text") {
		fieldtype = "textarea";
	} else if (datatype == "HTML") {
		fieldtype = "html";
	} else if (datatype == "color") {
		fieldtype = "color";
	} else if (datatype == "image") {
		fieldtype = "image";
	} else if (datatype == "federated") {
		fieldtype = "text";
	} else if (datatype == "foreign") {
		var sourceProperty = this.getRealPropertyForForeignProperty(propertyNd);
		fieldtype = this.uiGetFieldType4Property(sourceProperty);
	} else {
		fieldtype = "text";
	}

	if (datatype == "string" && propertyName == "classification") {
		fieldtype = "class structure";
	}

	return fieldtype;
};

Aras.prototype.uiMergeForeignPropertyWithSource = function ArasUiMergeForeignPropertyWithSource(foreignProperty, returnSource) {
	/*
	returns modified version of specified foreignProperty with some properties get from source
	Property
	*/
	if (!foreignProperty) {
		return null;
	}

	var dataType = this.getItemProperty(foreignProperty, 'data_type');
	if (dataType != 'foreign') {
		return null;
	}

	var tmpRes = foreignProperty.cloneNode(true);
	var sourcePropNd = this.getRealPropertyForForeignProperty(foreignProperty);

	if (returnSource) {
		return sourcePropNd;
	}
	var self = this;

	function copyProperty(propNm) {
		var tmpVal = self.getItemProperty(sourcePropNd, propNm);
		self.setItemProperty(tmpRes, propNm, tmpVal, false);
	}

	copyProperty("data_type");
	copyProperty("data_source");

	function copyAttribute(propNm, attrNm) {
		var tmpAttr = self.getNodeElementAttribute(sourcePropNd, propNm, attrNm);
		if (tmpAttr) {
			self.setNodeElementAttribute(tmpRes, propNm, attrNm, tmpAttr);
		}
	}

	copyAttribute("data_source", "keyed_name");
	copyAttribute("data_source", "type");
	copyAttribute("data_source", "name");

	this.setItemProperty(tmpRes, "readonly", "1", false);

	return tmpRes;
};

Aras.prototype.uiDrawFieldEx = function ArasUiDrawFieldEx(fieldNd, propNd, mode, itemTypeNd) {
	if (!fieldNd) {
		return false;
	}

	var fieldModel = this._getBaseDrawingModel("", mode, itemTypeNd, true, true);
	fieldModel.FieldInfo = fieldNd.xml;
	fieldModel.PropInfo = propNd ? propNd.xml : "";
	fieldModel = JSON.stringify(fieldModel);

	var xmlHttp = this.XmlHttpRequestManager.CreateRequest();
	xmlHttp.open("POST", this.getBaseURL() + "/Modules/aras.innovator.core.Form/PostField", false);
	xmlHttp.setRequestHeader("Content-Type", "application/json; charset=utf-8");
	xmlHttp.send(fieldModel);

	var content;
	if (xmlHttp.status == 200) {
		if (!content) {
			content = xmlHttp.responseText;
		}
	}
	return content;
};

Aras.prototype.uiGetFilteredListEx = function (fValueNds, filter) {
	if (!fValueNds) {
		return null;
	}
	if (filter === undefined) {
		filter = "";
	}

	if (filter === "") {
		return fValueNds;
	}

	var res = [];
	for (var i = 0; i < fValueNds.length; i++) {
		if (this.getItemProperty(fValueNds[i], "filter").search(filter) === 0) {
			res[res.length] = fValueNds[i];
		}
	}

	this.applySortOrder(res);
	return res;
};

Aras.prototype.uiPopulateFormWithItemEx = function (form, itemNd, itemTypeNd, isEditMode) {
	if (!form) {
		return false;
	}

	var doc = form.ownerDocument || form.document || form;
	if (!doc) {
		this.AlertError(this.getResource("", "ui_methods_ex.failed_get_parent_document_for_form"));
		return false;
	}

	var formWindow = doc.parentWindow ? doc.parentWindow : doc.defaultView;
	if (doc.readyState !== "complete") {
		formWindow.setTimeout(function () {
			this.uiPopulateFormWithItemEx(form, itemNd, itemTypeNd, isEditMode);
		}.bind(this), 10);
		return;
	}

	doc.isFormPopulated = false;

	if (!itemNd) {
		return false;
	}

	var iomItem = new Item();
	var i;

	iomItem.dom = itemNd.ownerDocument;
	iomItem.node = itemNd;
	doc.item = itemNd;
	doc.thisItem = iomItem;
	doc.itemID = itemNd.getAttribute("id");
	doc.isTemp = (itemNd.getAttribute("isTemp") == "1");

	if (isEditMode === undefined) {
		isEditMode = (doc.isTemp || this.getItemProperty(itemNd, "locked_by_id") == this.getCurrentUserID());
	}
	doc.isEditMode = isEditMode;

	if (!(formWindow.isFormTool || (formWindow.frameElement && formWindow.frameElement.isFormTool))) {
		var cssPropNm;
		for (var stepNum = 1; stepNum < 3; stepNum++) {
			cssPropNm = (stepNum == 1) ? "fed_css" : "css";

			var css = this.getItemProperty(itemNd, cssPropNm);
			if (css) {
				var ss = doc.styleSheets[doc.styleSheets.length - 1];
				var styleTmplt = new RegExp(/^\.(\w)+(\s)*\{(\w|\s|\:|\-|\#|\;)*\}$/); //look getItemStyles
				var styles = css.split("\n");
				var style;
				var classParts;

				for (i = 0; i < styles.length; i++) {
					style = styles[i];
					if (styleTmplt.test(style)) {
						if (ss.insertRule) {
							style = style.trim();
							ss.insertRule(style, ss.cssRules.length);
							ss.insertRule("input" + style, ss.cssRules.length);
							ss.insertRule("input[disabled]" + style, ss.cssRules.length);
							ss.insertRule("input[readonly]" + style, ss.cssRules.length);
						} else {
							classParts = style.split("{");
							style = classParts[1].split("}")[0].trim();
							ss.addRule(classParts[0], style);
							ss.addRule("input" + classParts[0], style);
							ss.addRule("input[disabled]" + classParts[0], style);
							ss.addRule("input[readonly]" + classParts[0], style);
						}
					}
				}
			}
		}
	}

	if (!itemTypeNd) {
		itemTypeNd = this.getItemTypeNodeForClient(itemNd.getAttribute("type"));
		if (!itemTypeNd) {
			return false;
		}
	}

	var propNds = itemTypeNd.selectNodes("Relationships/Item[@type='Property' and name!='' and " +
		"(not(@action) or (@action!='delete' and @action!='purge'))]");

	if (!propNds.length) {
		itemTypeNd = this.getItemTypeNodeForClient(itemNd.getAttribute("type"));
		if (!itemTypeNd) {
			return false;
		}
		propNds = itemTypeNd.selectNodes("Relationships/Item[@type='Property' and name!='' and " +
			"(not(@action) or (@action!='delete' and @action!='purge'))]");
	}

	var propNm;
	var elem;
	var propValue;
	var propDataType;
	var propPtrn;
	var workProp;
	var pattern;

	for (i = 0; i < propNds.length; i++) {
		if (this.getItemProperty(propNds[i], "data_type") === "foreign") {
			workProp = this.uiMergeForeignPropertyWithSource(propNds[i], true);
		} else {
			workProp = propNds[i];
		}

		propDataType = this.getItemProperty(workProp, "data_type");
		propPtrn = this.getItemProperty(workProp, "pattern");
		propNm = this.getItemProperty(propNds[i], "name");

		switch (propDataType) {
			case "decimal":
				pattern = this.getDecimalPattern(this.getItemProperty(workProp, "prec"), this.getItemProperty(workProp, "scale"));
				break;
			case "date":
				pattern = this.getDotNetDatePattern(propPtrn);
				break;
			default:
				pattern = null;
		}
		elem = formWindow.observersHash.getElementById(propNm + "_system");
		if (elem) {
			propValue = this.getItemProperty(itemNd, propNm);
			propValue = this.convertFromNeutral(propValue, propDataType, pattern);
			if (propDataType === "sequence" && propValue === "") {
				continue;
			}
			if (elem.value != propValue) {
				elem.setValue(propValue);
			} else if (propValue !== "") {
				elem.setValue("");
				elem.setValue(propValue);
			}
		}
	}

	this.uiPopulateInfoTableWithItem(itemNd, doc);
	var elems = doc.getElementsByName('sys_f_restricted_msg');
	var eventObj = doc.createEvent('Event');
	var eventType = 'onhelp';
	var currElem;

	eventObj.initEvent(eventType, true, true);
	for (i = 0; i < elems.length; i++) {
		currElem = elems[i];
		if (currElem.getAttribute(eventType)) {
			currElem.addEventListener(eventType, new formWindow.Function("event", currElem.getAttribute(eventType)));
			currElem.removeAttribute(eventType);
		}
		currElem.dispatchEvent(eventObj);
	}

	doc.isFormPopulated = true;

	try {
		if (formWindow.parent.updateMenuState) {
			formWindow.parent.updateMenuState();
		}
	} catch (excep) {
	}

	//to fire onformpopulated event.
	//if onformpopulated is defined on the window which contains just populated form then we call onformpopulated();
	if (formWindow && formWindow.onformpopulated && typeof (formWindow.onformpopulated) == "function") {
		formWindow.onformpopulated();
	}
};

Aras.prototype.uiNewItemEx = function (itemTypeName) {
	if (!itemTypeName) {
		return null;
	}

	var newItemNd = null;

	switch (itemTypeName) {
		case "SelfServiceReport":
			var existingWnd = this.uiFindAndSetFocusWindowEx(this.SsrEditorWindowId);
			if (existingWnd) {
				this.AlertError(this.getResource("", "ui_methods_ex.create_only_one_report_at_a_time").replace("{0}", existingWnd.itemID || ""));
				return null;
			}
			newItemNd = this.newItem(itemTypeName);
			newItemNd.setAttribute("use_custom_form", 1);
			this.itemsCache.addItem(newItemNd);
			break;
		case "RelationshipType":
			newItemNd = this.newRelationship(this.getRelationshipTypeId("RelationshipType"), null, false, null);
			this.setItemProperty(newItemNd, "related_id", null);
			break;
		default:
			newItemNd = this.newItem(itemTypeName);
			this.itemsCache.addItem(newItemNd);
			break;
	}

	if (newItemNd) {
		this.uiShowItemEx(newItemNd, "new");
	}

	return newItemNd;
};

Aras.prototype.uiNewItemExAsync = function (itemTypeId) {
	const aras = this;
	const itemTypeName = aras.getItemTypeName(itemTypeId);

	if (itemTypeName === 'File') {
		return aras.vault.selectFile().then(function(item) {
			const fileNode = aras.newItem('File', item);
			aras.uiShowItemEx(fileNode, 'new');
			aras.itemsCache.addItem(fileNode);
		});
	}

	if (!window.showModalDialog) {
		const itemTypeNode = aras.getItemTypeForClient(itemTypeId, 'id').node;
		const isPolyItem = aras.isPolymorphic(itemTypeNode);

		if (isPolyItem) {
			var itemType=aras.getItemTypeForClient(itemTypeName).node;
			var itemTypesList = this.getMorphaeList(itemType);
			console.log(itemTypesList);
			console.log(itemTypesList.length)
			if(itemTypesList.length==1){
				var new_itemNd = aras.newItem(itemTypesList[0].name);
				aras.itemsCache.addItem(new_itemNd);
				aras.uiShowItemEx(new_itemNd, 'new');
			}
			else{
				return aras.newItem(itemTypeName).then(function(node) {
					if (node) {
						aras.itemsCache.addItem(node);
						aras.uiShowItemEx(node, 'new');
					}
				});
			}
			
		}
	}

	return Promise.resolve(aras.uiNewItemEx(itemTypeName));
};

Aras.prototype.makeItemsGridBlank = function ArasMakeItemsGridBlank(saveSetups) {
	//this method is for internal purposes only.
	if (saveSetups === undefined) {
		saveSetups = true;
	}

	var mainWindow = this.getMainWindow();
	try {
		var w = mainWindow.work;
		if (w) {
			if (w.location) {
				if (!saveSetups) {
					if (w.saveSetups) {
						w.saveSetups = function () { };
					}
				}

				if (w.searchContainer) {
					w.searchContainer.onEndSearchContainer();
				}

				w.location.replace(this.getScriptsURL() + "blank.html");
			}
			w.isItemsGrid = false;
		}
	} catch (excep) {
	}

	var m;
	try {
		m = mainWindow.menu;
	} catch (ex) {
	}
	if (m && m.setAllControlsEnabled) {
		m.setAllControlsEnabled(false);
	}
};

Aras.prototype.uiPopulateInfoTableWithItem = function ArasUiPopulateInfoTableWithItem(sourceItm, doc, sendThumbnailRequestHandler, sendLCStateRequestHandler) {
	var table = doc.getElementById('itemInfoTable');
	var propertyName = 'thumbnail';
	var propertyContainer = doc.getElementById(propertyName + '_row');
	if (!table) {
		return;
	}

	var itProps = table.getElementsByTagName('span');
	var itPropsIndex;
	var itProperty;
	var newItProperty;
	if (!sourceItm) {
		for (itPropsIndex = 0; itPropsIndex < itProps.length; itPropsIndex++) {
			itProperty = itProps[itPropsIndex].getAttribute("id");
			if (!itProperty) {
				continue;
			}

			newItProperty = itProperty.replace("itemProps$", "");
			if (newItProperty != itProperty) {
				doc.getElementById(itProperty).innerHTML = "<b></b>";
			}
		}

		if (propertyContainer) {
			propertyContainer.style.display = "none";
		}

		return;
	}

	var typeName = sourceItm.getAttribute("type");
	var currItmTypeInfo = this.getItemTypeNodeForClient(typeName, "name");
	var shortDtPtrn = this.getDotNetDatePattern("short_date");

	var self = this;

	function uiPopulateInfoTableItemPropsHelper(newItProperty, itProperty, currItmTypeInfo, sourceItm, propertyValue, doc, shortDtPtrn) {
		if (propertyValue === "") {
			var propertyInfo = currItmTypeInfo.selectSingleNode("Relationships/Item[name='" + newItProperty + "']");
			if (propertyInfo) {
				var propertyType = propertyInfo.selectSingleNode("data_type");
				propertyType = propertyType ? propertyType.text : "";

				switch (propertyType) {
					case "item":
						propertyValue = sourceItm.selectSingleNode(newItProperty + "/@keyed_name");
						propertyValue = (propertyValue ? propertyValue.text : "");
						break;

					case "date":
						propertyValue = self.convertFromNeutral(self.getItemProperty(sourceItm, newItProperty), "date", shortDtPtrn);
						break;

					default:
						propertyValue = self.getItemProperty(sourceItm, newItProperty);
						propertyValue = (propertyValue ? propertyValue : "");
				}
			}
		}
		doc.getElementById(itProperty).innerHTML = propertyValue;
	}

	var uiPopulateInfoTableItemPropsHelperInvoker = function (propertyValue) {
		uiPopulateInfoTableItemPropsHelper(newItProperty, itProperty, currItmTypeInfo, sourceItm, propertyValue, doc);
	};

	var propertyValue;
	for (itPropsIndex = 0; itPropsIndex < itProps.length; itPropsIndex++) {
		itProperty = itProps[itPropsIndex].getAttribute("id");
		if (!itProperty) {
			continue;
		}

		newItProperty = itProperty.replace("itemProps$", "");
		propertyValue = "";

		if (newItProperty != itProperty) {
			switch (newItProperty) {
				case "generation":
					propertyValue = this.getItemProperty(sourceItm, "generation");
					if (propertyValue === "") {
						propertyValue = "1";
					}
					break;

				case "state":
					var itemId = self.getItemProperty(sourceItm, "current_state");
					this.getLCStateLabel(itemId, sendLCStateRequestHandler, uiPopulateInfoTableItemPropsHelperInvoker);
					continue;
			}
			uiPopulateInfoTableItemPropsHelper(newItProperty, itProperty, currItmTypeInfo, sourceItm, propertyValue, doc, shortDtPtrn);
		}
	}

	sendThumbnailRequestHandler = sendThumbnailRequestHandler || function (soapBody, callback) {
		var response = this.soapSend('GetItem', soapBody);
		var itemAdditionalInfo = response.results.selectNodes('//Result/Item');
		callback(itemAdditionalInfo);
	}.bind(this);

	if (propertyContainer) {
		propertyValue = "";
		var domElement = doc.getElementById('itemProps$' + propertyName);
		var showThumbnail = function() {
			if (propertyValue) {
				if (propertyValue.toLowerCase().indexOf('vault:\/\/\/\?fileid=') === 0) {
					var fileId = propertyValue.replace(/vault:\/\/\/\?fileid\=/i, '');
					propertyValue = this.IomInnovator.getFileUrl(fileId, this.Enums.UrlType.SecurityToken);
				}

				domElement.src = propertyValue;
				propertyContainer.style.display = '';
			} else {
				domElement.src = '';
				propertyContainer.style.display = 'none';
			}
		}.bind(this);

		//immediately hide previous image
		propertyContainer.style.display = "none";
		domElement.src = "";

		var cacheItem = this.itemsCache.getItem(sourceItm.getAttribute("id"));
		if (sourceItm.selectSingleNode(propertyName) || cacheItem) {
			propertyValue = this.getItemProperty((cacheItem || sourceItm), propertyName, "");
			showThumbnail();
		} else {
			var sourceItemId = this.getItemProperty(sourceItm, "id");

			sendThumbnailRequestHandler("<Item type=\"" + typeName + "\" action=\"get\" id=\"" + sourceItemId + "\" select=\"" + propertyName + "\"/>", function (itemNds) {
				if (1 === itemNds.length) {
					propertyValue = this.getItemProperty(itemNds[0], propertyName, "");
					var thumbnail = sourceItm.appendChild(sourceItm.ownerDocument.createElement(propertyName));
					thumbnail.text = propertyValue;
					showThumbnail();
				}
			}.bind(this));
		}
	}
};

Aras.prototype.uiDrawItemInfoTable = function ArasUiDrawItemInfoTable(itemTypeNd, propsHelper, propertiesArray) {
	var defaultProperties = ["created_by_id", "created_on", "modified_by_id", "modified_on", "locked_by_id", "major_rev", "release_date", "effective_date", "generation", "state"];
	propertiesArray = propertiesArray || defaultProperties;
	propertiesArray = propertiesArray.filter(function(val) { return val !== ""; });
	var resourcesObject = this.getResources('core', propertiesArray.map(function (propertyId) {
		return 'item_info_table.' + propertyId + '_txt';
	}));

	var propertiesHelper = {
		properties: propertiesArray.map(function (propertyId) {
			return {
				id: propertyId,
				label: resourcesObject["item_info_table." + propertyId + "_txt"]
			};
		}),
		showThumbnails: false
	};
	Object.assign(propertiesHelper, propsHelper);

	return this.uiDrawItemInfoTableImpl(itemTypeNd, propertiesHelper);
};

Aras.prototype.uiDrawItemInfoTable4ItemsGrid = function ArasUiDrawItemInfoTable4ItemsGrid(itemTypeNd, propertiesHelper) {
	if (!propertiesHelper) {
		propertiesHelper = {
			showThumbnails: true
		};
	}
	return this.uiDrawItemInfoTable(itemTypeNd, propertiesHelper);
};

Aras.prototype.uiDrawItemInfoTableImpl = function ArasUiDrawItemInfoTableImpl(itemTypeNd, propertiesHelper) {
	var largeIconImg = "";
	var label = "";
	var isVersionable = false;
	if (itemTypeNd) {
		largeIconImg = this.getItemProperty(itemTypeNd, "large_icon");

		if (largeIconImg.toLowerCase().indexOf("vault:\/\/\/\?fileid=") === 0) {
			var fileId = largeIconImg.replace(/vault:\/\/\/\?fileid\=/i, "");
			largeIconImg = this.IomInnovator.getFileUrl(fileId, this.Enums.UrlType.SecurityToken);
		}

		label = this.getItemProperty(itemTypeNd, "label") || this.getItemProperty(itemTypeNd, "name");
		label = this.EscapeSpecialChars(label);
		isVersionable = this.getItemProperty(itemTypeNd, "is_versionable") == "1";
	}

	var imgSrc = largeIconImg ? " src='" + largeIconImg + "'" : "";
	var html = "<div class='properties-block' style='width: 170px !important;'>" +
				"<div class='prop-header'>" +
					"<h2><span id='label_span'>" + label + "</span></h2>" +
					"<img id='large_icon_img' name='large_icon_img' hspace='20' vspace='20'" + imgSrc + " style='display: block; visibility:" +
					(largeIconImg ? "visible" : "hidden") + "; height: " + (largeIconImg ? "auto" : "30px") + "; width: " + (largeIconImg ? "auto" : "28px") + "; max-width: 45px; max-height: 45px'/>" +
				"</div>" +
				"<div id='itemInfoTable' class='prop-body'>";

	html = propertiesHelper.properties.reduce(function (accumulator, property) {
		var displayStyle = ((property.id === "release_date" || property.id === "effective_date") && !isVersionable) ? "style='display:none;'" : "";
		accumulator += "<div id='" + property.id + "_row' " + displayStyle + " class='prop-field'>" +
			"<span class='prop-label'>" + this.EscapeSpecialChars(property.label) + "</span>" +
			"<span id='itemProps$" + property.id + "' class='prop-value'></span></div>";
		return accumulator;
	}.bind(this), html);

	if (propertiesHelper.showThumbnails) {
		var propertyName = "thumbnail";
		var propertyNode = itemTypeNd.selectSingleNode("Relationships/Item[@type='Property' and name='" + propertyName + "' and data_type='image']");
		if (propertyNode) {
			html += "<div class='prop-field' id='" + propertyName + "_row' style='display:none;'>" +
				"<img id='itemProps$" + propertyName + "' src='' style='max-width:150px; max-height:150px; margin-top: 5px;'/>" +
				"</div>";
		}
	}

	html += "</div></div>";
	return html;
};

Aras.prototype.uiGetItemInfoTable = function ArasUiGetItemInfoTable(itemTypeNd, itemNd, makeTableForItm, appendIdToItmTable, widthsHash, propsArr) {
	var propertiesHelper = {
		showThumbnails: false
	};

	if (!itemNd && !makeTableForItm) {
		propsArr = [];
	} else {
		propsArr = propsArr || ["created_by_id", "created_on", "modified_by_id", "modified_on", "locked_by_id", "major_rev", "release_date", "effective_date", "generation", "state", "id"];

		if (!appendIdToItmTable && propsArr.indexOf('id') > -1) {
			propsArr.splice(propsArr.indexOf('id'), 1);
		}
	}

	return this.uiDrawItemInfoTable(itemTypeNd, propertiesHelper, propsArr);
};

//ItemTypeValue may be ItemTypeName or ItemTypeNode
Aras.prototype.saveUICommandHistoryIfNeed = function ArasSaveUICommandHistoryIfNeed(itemTypeValue, itemNd, uiCmd, formName) {
	if (!itemNd || this.isNew(itemNd)) {
		return;
	}
	var itemTypeNode;
	var itemTypeName;

	if (typeof itemTypeValue == "object") {
		itemTypeNode = itemTypeValue;
		itemTypeName = itemNd.getAttribute("type");
	} else if (typeof itemTypeValue == "string") {
		itemTypeNode = this.getItemTypeNodeForClient(itemTypeValue);
		itemTypeName = itemTypeValue;
	} else {
		return;
	}

	var historyAction;
	switch (uiCmd) {
		case "view":
			historyAction = "FormView";
			break;
		case "print":
			historyAction = "FormPrint";
			break;
		default:
			return;
	}

	if (itemTypeName != "File") {
		var historyTemplate = itemTypeNode.selectSingleNode("history_template");
		if (!historyTemplate || !historyTemplate.selectSingleNode(
			"Item[@type='History Template']/Relationships/Item[@type='History Template Action']/related_id/Item[@type='History Action' and name='" + historyAction + "']")) {
			return;
		}
	}

	var q = this.newIOMItem(itemTypeName, "AddHistory");
	q.setAttribute("id", itemNd.getAttribute("id"));
	q.setProperty("action", historyAction);
	q.setProperty("form_name", formName);

	// Send synchronous request by reason of IR-037684 (IE bug 877525)
	var result = this.soapSend("ApplyItem", q.dom.xml);
	if (result.getFaultCode() != "0") {
		this.AlertError(result);
	}
};

Aras.prototype.getElementsById = function ArasGetElementsById(doc, tag, id) {
	result = [];
	var elements = doc.getElementsByTagName(tag);

	for (var i = 0, j = 0; i < elements.length; i++) {
		if (elements[i].id == id) {
			result[j++] = elements[i];
		}
	}
	return result;
};

/// <summary>
/// This function is a workaround for IE behavior of displaying liquid tables.
/// To display objects that should take all available space on the page usually we can shrink it to 100%.
/// But if there are any other elementswith fixed height on the page we can't set our object height to 100% and should calculate
/// size for it.
/// There are some constraints for markup that will use this function to resize object:
///
///	0. Object should have table as container.
///	1. Need to set height in px for object and object container both for objects with fixed height;
///	   It is need to set fixed object height and its position in container.
///	2. Need to set height in % for object and object container both for objects with relative height;
///	3. Need to set html, body height to 100% and margin and padding to 0px;
///	4. It is possible to have elements before liquid table, but not after it;
///	5. Need to resize not td, but an object in this td to avoid its blinking in IE8;
///	6. Need to set a doctype for the page.
/// </summary>
/// <example>
///   <code language="html">
///<![CDATA[<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 4.01//EN" "http://www.w3.org/TR/html4/strict.dtd">
///<html>
///	<script type="text/javascript">
///		// Call fix function every 100ms to resize liquid container.
///		// Attach event handler that should stop calling fix function.
///		// 100ms interval choosed as most useful interval to update height
///		// without noticeable delay.
///		onload = function OnloadHandler()
///		{
///			interval = setInterval(fix, 100);
///			window.attachEvent('onbeforeunload', onbeforeunload_handler);
///		}
///
///		// For better responsibility we could call it in onresize event handler;
///		// But it is not required.
///		onresize = function OnresizeHandler()
///		{
///			fix();
///		}
///
///		// Stop fixing height before unloading page because aras object becomes
///		// unavailable and accessing to it causes error and
///		// not cleared interval could lead to memory leaks.
///		//
///		var onbeforeunload_handler = function ()
///		{
///			if (window.interval)
///			{
///				clearInterval(interval);
///			}
///		}
///
///		// Create a simple wrapper that calls fixLiquidContainerHeight
///		// passing in current document object and element that need to be resized.
///		function fix()
///		{
///			var el = document.getElementById("grid");
///			aras.fixLiquidContainerHeight(document, el);
///		}
///	</script>
///</html>]]>
/// </code>
/// </example>
Aras.prototype.fixLiquidContainerHeight = function ArasFixLiquidContainerHeight(doc, el, obj) {
	if (!el || !el.parentNode || !el.parentNode.offsetParent) {
		return;
	}
	if (!obj) {
		obj = el;
	}

	var parentEl = el.parentNode;
	if (parentEl.tagName == "TBODY") {
		var tableEl = parentEl.offsetParent;
		var containerHeight = doc.documentElement.clientHeight ? doc.documentElement.clientHeight : doc.documentElement.offsetHeight;

		containerHeight -= tableEl.offsetTop;
		var newHeight = containerHeight;
		var rows = parentEl.rows;
		for (var i = 0, L = rows.length; i < L; i++) {
			var row = rows[i];
			if (row != el && row.style.display != "none") {
				newHeight -= row.offsetHeight;
			}
		}
		newHeight = newHeight > 0 ? newHeight : 0;
		if (obj.style.pixelHeight != newHeight) {
			obj.style.height = newHeight + "px";
		}

		newHeight = containerHeight;
		newHeight = newHeight > 0 ? newHeight : 0;
		if (tableEl.style.pixelHeight != newHeight) {
			tableEl.style.height = newHeight + "px";
		}
	} else {
		this.fixLiquidContainerHeight(doc, parentEl, obj);
	}
};

Aras.prototype.SelectFileFromPackage = function ArasSelectFileFromPackage(methodName, isMultiselect) {
	if (isMultiselect === undefined) {
		isMultiselect = false;
	}
	// get file from this instance
	var methodArgs = {};
	methodArgs.multiselect = isMultiselect;
	methodArgs.aras = this;
	var itemIds = this.evalItemMethod(methodName, "", methodArgs);

	if (!itemIds || itemIds.length === 0) {
		return;
	}

	query = new Item("File", "get");
	query.setAttribute("idlist", itemIds);
	query = query.apply();
	if (query.isError()) {
		this.AlertError(query.getErrorString());
		return;
	}

	var count = query.getItemCount();
	for (var i = 0; i < count; i++) {
		var itemFile = query.getItemByIndex(i);
		itemFile.setAttribute("action", "FE_CopyFileToContainer");
	}
	return isMultiselect ? query : query.node;
};

Aras.prototype.getElementsByClass = function ArasGetElementsByClass(searchClass, node) {
	return node.getElementsByClassName(searchClass);
};

Aras.prototype.updateDomSelectLabel = function ArasUpdateDomSelectLabel(domSelect) {
	var span = domSelect.parentNode.getElementsByTagName("span")[0];
	span.innerHTML = domSelect.options[domSelect.selectedIndex] ? domSelect.options[domSelect.selectedIndex].text : "";
};

/*
* isNeedToDisplaySSVCSidebar - function defines is it necessary to display the SSVC sidebar.
*
* parameters:
* itemNd   - xml node of item to find correspondent view
* formType - string, representing mode: 'add', 'view', 'edit' or 'print'
*/
Aras.prototype.isNeedToDisplaySSVCSidebar = function ArasIsNeedToDisplaySSVCSidebar(itemNd, formType) {
	function findMaxPriorityView(itemType, roles, formType) {
		var tryGetClassificationViewWithoutFormType = function (classification) {
			xp = "Relationships/Item[@type='View' and " + strRoles + "][form_classification='" + classification + "']";
			return itemType.selectNodes(xp);
		};

		var returnNodes;
		if (typeof (roles) == "string") {
			var tmpRoles = roles;
			roles = [];
			roles.push(tmpRoles);
		}
		var strRoles = "(role='" + roles.join("' or role='") + "')";

		if (classification) {
			var xp = "Relationships/Item[@type='View' and " + strRoles + " and type='" + formType + "'][form_classification='" + classification + "']";
			var nodes = itemType.selectNodes(xp);
			returnNodes = nodes.length > 0 ? nodes : tryGetClassificationViewWithoutFormType(classification);
		}

		if (!(returnNodes && (returnNodes.length !== 0))) {
			returnNodes = itemType.selectNodes("Relationships/Item[@type='View' and string(form_classification)='' and " + strRoles + " and type='" + formType + "']");
		}

		if (returnNodes.length === 0) {
			return "";
		}

		var currView = returnNodes[0];
		var currPriority = self.getItemProperty(returnNodes[0], "display_priority");
		if (currPriority === "") {
			currPriority = Number.POSITIVE_INFINITY;
		}

		for (var i = 1; i < returnNodes.length; i++) {
			var priority = self.getItemProperty(returnNodes[i], "display_priority");
			if (priority === "") {
				priority = Number.POSITIVE_INFINITY;
			}

			if (currPriority > priority) {
				currPriority = priority;
				currView = returnNodes[i];
			}
		}

		return currView;
	}

	function findMaxPriorityViewForItemType(anItemType, formType) {
		var res = findMaxPriorityView(anItemType, identityId, formType);
		if (res) {
			return res;
		}

		if (formType != "default") {
			res = findMaxPriorityView(anItemType, identityId, "default");
			if (res) {
				return res;
			}
		}

		res = findMaxPriorityView(anItemType, userIdentities, formType);
		if (res) {
			return res;
		}

		if (formType != "default") {
			res = findMaxPriorityView(anItemType, userIdentities, "default");
			if (res) {
				return res;
			}
		}

		return undefined;
	}

	if (!this.commonProperties.IsSSVCLicenseOk) {
		return "";
	}

	if (!itemNd) {
		return "";
	}
	if (!formType || formType.search(/^default$|^add$|^view$|^edit$|^print$|^search$/) == -1) {
		return "";
	}

	var userIdentities = this.getIdentityList().split(",");
	if (userIdentities.length === 0) {
		return "";
	}

	var userNd = null;
	var tmpUserID = this.getCurrentUserID();

	if (tmpUserID == this.getUserID()) {
		userNd = this.getLoggedUserItem();
	} else {
		userNd = this.getItemFromServerWithRels("User", tmpUserID, "id", "Alias", "related_id(id)", true).node;
	}

	if (!userNd) {
		return "";
	}

	var identityNd = userNd.selectSingleNode("Relationships/Item[@type='Alias']/related_id/Item[@type='Identity']");
	if (!identityNd) {
		return "";
	}

	var identityId = identityNd.getAttribute("id");
	var itemTypeName = itemNd.getAttribute("type");
	var itemTypeNd = this.getItemTypeNodeForClient(itemTypeName, "name");
	var classification;
	var classificationNode = itemNd.selectSingleNode("classification");
	if (classificationNode) {
		classification = classificationNode.text;
	}

	var self = this;

	var view = findMaxPriorityViewForItemType(itemTypeNd, formType);
	if (!view && this.getItemProperty(itemTypeNd, "implementation_type") == "polymorphic") {
		var itemtypeId = this.getItemProperty(itemNd, "itemtype");
		if (itemtypeId) {
			itemTypeNd = this.getItemTypeNodeForClient(itemtypeId, "id");
			if (itemTypeNd) {
				view = findMaxPriorityViewForItemType(itemTypeNd, formType);
			}
		}
	}
	return !view ? false : this.getItemProperty(view, "show_ssvc") === "1";
};

Aras.prototype.uiIsParamTabVisibleEx = function Aras_uiIsParamTabVisibleEx(itemNd, itemTypeName) {
	var mode = "0";
	var res = false;
	if (itemNd && itemNd.xml && !itemTypeName) { itemTypeName = itemNd.getAttribute("type"); }
	if (!(itemTypeName && itemNd)) return res;
	var itemTypeNd = this.getItemTypeNodeForClient(itemTypeName);
	if (!itemTypeNd || !itemTypeNd.xml) return res;
	var show_parameters_tabNd = itemTypeNd.selectSingleNode("show_parameters_tab");
	var show_parameters_tab = "1";
	if (show_parameters_tabNd) show_parameters_tab = show_parameters_tabNd.text;

	switch (show_parameters_tab) {
		case "0":
			break;
		case "1":
			mode = "1";
			var class_structureNd = itemTypeNd.selectSingleNode("class_structure");
			if (class_structureNd) {
				var classificationNd = itemNd.selectSingleNode("classification");
				var classification = (classificationNd) ? classificationNd.text : "";
				if (!this.isClassPathRoot(classification)) {
					var propsOfClassPath = this.selectPropNdsByClassPath(classification, itemTypeNd);
					if (propsOfClassPath && propsOfClassPath.length > 0) {
						var props = [];
						for (var i = 0; i < propsOfClassPath.length; i++) {
							var prop = propsOfClassPath[i];
							var class_path = this.getItemProperty(prop, "class_path");
							if (!this.isClassPathRoot(class_path))
								props.push(prop);
						}

						res = (props.length > 0);
					}
				}
			}
			break;
		case "2":
			mode = "2";
			res = true;
			break;
	}
	return {
		mode:mode,
		show:res
	};
};

function appendParameter(param, value) {
	if (param !== "") {
		param += "&";
	}
	param += value;
	return param;
}

/** workflow_methods.js **/
// © Copyright by Aras Corporation, 2004-2007.

/*-- newWorkflowMap
*
*   Method to create a new workflow map
*
*/
Aras.prototype.newWorkflowMap = function() {
	var statusId = this.showStatusMessage('status', this.getResource('', 'workflow_methods.creating_workflow_map'), '../images/Progress.gif');
	var res = this.soapSend('ApplyItem', '<Item type="Method" action="New Workflow Map"/>');
	if (statusId) {
		this.clearStatusMessage(statusId);
	}

	if (res.getFaultCode() !== 0) {
		this.AlertError(res);
		return false;
	}

	var item = res.results.selectSingleNode(this.XPathResult('/Item'));
	item.setAttribute('levels', 2);
	item.setAttribute('loaded', '1');
	item.setAttribute('isTemp', '1');
	var itemID = item.getAttribute('id');
	return item;
};

/*-- initiateWorkflow
*
*   Method to initiate a new workflow process
*   workflowMapID   = the id for the Workflow Map to be used as a template
*   item           = the item for which new workflow process should be created
*
*/
Aras.prototype.initiateWorkflow = function(workflowMapID, item) {
	var statusId = this.showStatusMessage('status', this.getResource('', 'workflow_methods.initiating_workflow'), '../images/Progress.gif');

	var body = '<WorkflowMap>' + workflowMapID + '</WorkflowMap>' +
				'<Item type="' + item.getAttribute('type') +
				'" id="' + item.getAttribute('id') + '" />';

	var res = this.soapSend('InitiateWorkflow', body);
	if (statusId) {
		this.clearStatusMessage(statusId);
	}

	if (res.getFaultCode() !== 0) {
		this.AlertError(res);
		return false;
	}

	var process = res.results.selectSingleNode('//Item');
	process.setAttribute('levels', '1');
	process.setAttribute('loaded', '1');

	var workflow = this.newRelationship(this.getItemFromServerByName('RelationshipType', 'Workflow', 'id').getID(), item);
	var relatedId = workflow.selectSingleNode('related_id');
	relatedId.replaceChild(process.cloneNode(true), relatedId.selectSingleNode('Item'));
	this.setNodeElement(workflow, 'source_type', this.getItemFromServerByName('ItemType', item.getAttribute('type'), 'id').getID());
	return true;
};

/*-- startWorkflow
*
*   Method to start the workflow process
*   workflowProcess  = the workflow process that should be started
*
*/
Aras.prototype.startWorkflow = function(workflowProcess) {
	var statusId = this.showStatusMessage('status', this.getResource('', 'workflow_methods.starting_workflow_process'), '../images/Progress.gif');
	var body = '<Item type="Workflow Process" id="' + workflowProcess.getAttribute('id') + '" action="StartWorkflow"/>';
	var res = this.soapSend('ApplyItem', body);
	if (statusId) {
		this.clearStatusMessage(statusId);
	}

	if (res.getFaultCode() !== 0) {
		this.AlertError(res);
		return false;
	}

	var result = res.results.selectSingleNode(this.XPathResult());
	if (result.text !== 'Ok') {
		return false;
	} else {
		return true;
	}
};

/*-- stopWorkflow
*
*   Method to stop the workflow process
*   workflowProcess  = the workflow process that should be stopped
*
*/
Aras.prototype.stopWorkflow = function(workflowProcess) {
	var statusId = this.showStatusMessage('status', this.getResource('', 'workflow_methods.starting_workflow_process'), '../images/Progress.gif');
	var body = '<Item type="Workflow Process" id="' + workflowProcess.getAttribute('id') + '" action="StopWorkflow" />';
	var res = this.soapSend('ApplyItem', body);
	if (statusId) {
		this.clearStatusMessage(statusId);
	}

	if (res.getFaultCode() !== 0) {
		this.AlertError(res);
		return false;
	}

	var result = res.results.selectSingleNode(this.XPathResult());
	if (result.text !== 'Ok') {
		return false;
	} else {
		return true;
	}
};

/*-- activateActivity
*
*   Method to activate the activity
*   activity  = the activity to be activated
*
*/
Aras.prototype.activateActivity = function(activity) {
	var statusId = this.showStatusMessage('status', this.getResource('', 'workflow_methods.activating_activity'), '../images/Progress.gif');
	var body = '<Item type="Activity" id="' + activity.getAttribute('id') + '" action="ActivateActivity" />';
	var res = this.soapSend('ApplyItem', body);
	if (statusId) {
		this.clearStatusMessage(statusId);
	}

	if (res.getFaultCode() !== 0) {
		this.AlertError(res);
		return false;
	}

	var result = res.results.selectSingleNode(this.XPathResult());
	if (result.text !== 'Ok') {
		return false;
	} else {
		return true;
	}
};

/*-- evaluateActivity
*
*   Method to close the activity
*   activity  = the activity to be closed
*   path      = path that should be followed
*
*/
Aras.prototype.evaluateActivity = function(body) {
	var statusId = this.showStatusMessage('status', this.getResource('', 'workflow_methods.closing_activity'), '../images/Progress.gif');
	var res = this.soapSend('EvaluateActivity', body);
	if (statusId) {
		this.clearStatusMessage(statusId);
	}

	if (res.getFaultCode() !== 0) {
		this.AlertError(res);
		return false;
	}

	var result = res.results.selectSingleNode(this.XPathResult());
	if (result.text !== 'Ok') {
		return false;
	} else {
		return true;
	}
};

/*-- getAssignedActivities
*
*   Returns the Active and Pending Activity items for the user.
*   The users Activities are those assigned to an Identity for which the user is a Member
*
*/
Aras.prototype.getAssignedActivities = function(inBasketViewMode) {
	var body = '<inBasketViewMode>' + inBasketViewMode + '</inBasketViewMode>';
	var statusId = this.showStatusMessage('status', this.getResource('', 'workflow_methods.getting_user_activities'), '../images/Progress.gif');
	var res = this.soapSend('GetAssignedActivities', body);
	if (statusId) {
		this.clearStatusMessage(statusId);
	}

	if (res.getFaultCode() !== 0) {
		this.AlertError(res);
		return false;
	}
	return res.results.selectNodes(this.XPathResult('/Item'));
};

/*-- loadProcessInstance
*
*   Returns an applet ready XML string ofthe running workflow instance.
*
*/
Aras.prototype.loadProcessInstance = function ArasLoadProcessInstance(ProcessId, ActivityId) {
	var statusId = this.showStatusMessage('status', this.getResource('', 'workflow_methods.loading_process_map'), '../images/Progress.gif');

	var body = '<Item type="Workflow Process" pid="' + ProcessId + '" aid="' + ActivityId + '"  />';
	var res = this.soapSend('LoadProcessInstance', body);
	if (statusId) {
		this.clearStatusMessage(statusId);
	}

	if (res.getFaultCode() !== 0) {
		this.AlertError(res);
		return false;
	}
	return res.results;
};

/*-- BuildProcessReport
*
*   Returns an HTML string ofthe running workflow instance - sign-off History
*
*/
Aras.prototype.BuildProcessReport = function(ProcessId) {
	var statusId = this.showStatusMessage('status', this.getResource('', 'workflow_methods.loading_process_statistics'), '../images/Progress.gif');
	var body = '<Item type="Workflow Process" id="' + ProcessId + '" />';
	var res = this.soapSend('BuildProcessReport', body);
	if (statusId) {
		this.clearStatusMessage(statusId);
	}

	if (res.getFaultCode() !== 0) {
		this.AlertError(res);
		return false;
	}
	return res.results;
};

/*-- StartDefaultWorkflow
*
*   Finds the Default Workflow Map for the passed itemType and instance,   and
*   creates an instance of that Workflow and starts it.
*
*/
Aras.prototype.StartDefaultWorkflow = function(ItemId, ItemType, ItemTypeId) {
	var statusId = this.showStatusMessage('status', this.getResource('', 'workflow_methods.starting_default_workflow'), '../images/Progress.gif');
	var body = '<Item id="' + ItemId + '"  type="' + ItemType + '" typeId="' + ItemTypeId + '" />';
	var res = this.soapSend('StartDefaultWorkflow', body);
	if (statusId) {
		this.clearStatusMessage(statusId);
	}

	if (res.getFaultCode() !== 0) {
		this.AlertError(res);
		return false;
	}
	return res.results;
};

/*-- StartNamedWorkflow
*
*   Starts an instance of a Workflow for a specified item
*   WorkflowMap ID and the Item ID must be passed as arguments
*
*/
Aras.prototype.StartNamedWorkflow = function(ItemId, ItemType, ItemTypeId, WorkflowMapId) {
	var statusId = this.showStatusMessage('status', this.getResource('', 'workflow_methods.starting_named_workflow'), '../images/Progress.gif');
	var body = '<Item id="' + ItemId + '"  type="' + ItemType + '" typeId="' + ItemTypeId + '" WorkflowMapId="' + WorkflowMapId + '" />';
	var res = this.soapSend('StartNamedWorkflow', body);
	if (statusId) {
		this.clearStatusMessage(statusId);
	}

	if (res.getFaultCode() !== 0) {
		this.AlertError(res);
		return false;
	}
	return res.results;
};

/*-- ReAssignActivity
*
*   ReAssigns an Activity to a new Identity
*   Activity ID and the Identity ID must be passed as arguments
*
*/
Aras.prototype.ReAssignActivity = function(ActivityId, IdentityId) {
	var statusId = this.showStatusMessage('status', this.getResource('', 'workflow_methods.reassigning_activity'), '../images/Progress.gif');
	var body = '<Item ActivityId="' + ActivityId + '"  IdentityId="' + IdentityId + '" />';
	var res = this.soapSend('ReAssignActivity', body);
	if (statusId) {
		this.clearStatusMessage(statusId);
	}

	if (res.getFaultCode() !== 0) {
		this.AlertError(res);
		return false;
	}
	return res.results;
};

/*-- ValidateVote
*
*   checks either the Password or E-Signature for a user
*   Arguments are:  MD5 encrypted string +  "password" or esignature"
*     returns      pass   or     fail
*/
Aras.prototype.ValidateVote = function(incoming, mode) {
	var statusId = this.showStatusMessage('status', this.getResource('', 'workflow_methods.validating_authentication'), '../images/Progress.gif');
	var body = '<Item incoming="' + incoming + '" mode="' + mode + '" />';
	var res = this.soapSend('ValidateVote', body);
	if (statusId) {
		this.clearStatusMessage(statusId);
	}

	if (res.getFaultCode() !== 0) {
		this.AlertError(res);
		return false;
	}
	return res.results;
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

/** PopulateDocByLabels.js **/
function PopulateDocByLabels(doc, aras, solution) {
	if (!doc) {
		doc = document;
	}
	if (!aras) {
		aras = parent.aras ? parent.aras : parent.parent.aras;
	}
	if (!solution) {
		solution = '';
	}

	if (!aras || !doc) {
		return;
	}

	var allElm = doc.all || document.getElementsByTagName('*');
	var k;
	var s;
	var obj;
	for (var i = 0; i < allElm.length; i++) {
		obj = allElm[i];
		if (obj && obj.attributes && obj.attributes['aras_ui_resource_key']) {
			k = obj.attributes['aras_ui_resource_key'].value;
			s = aras.getResource(solution, k);
			if (k.indexOf('_html_value', k.length - 12) > -1) {
				obj.value = s;
			} else {
				obj.innerHTML = s;
			}
		}
	}
}

/** sp_functions.js **/
// © Copyright by Aras Corporation, 2011-2013
const MethodCompatibilityMode = function(currentServerVersion, currentClientRevision, arasObj) {
	var serverVersion = currentServerVersion.substring(0, currentServerVersion.lastIndexOf('.'));
	var clientVersion = currentClientRevision.substring(0, currentClientRevision.lastIndexOf('.'));
	if (clientVersion !== serverVersion) {
		throw new Error(1, arasObj.getResource('', 'sp_functions.incompatible_functions'));
	}
};

/** ../vendors/BigInteger.min.js **/
var bigInt=function(undefined){"use strict";var BASE=1e7,LOG_BASE=7,MAX_INT=9007199254740992,MAX_INT_ARR=smallToArray(MAX_INT),LOG_MAX_INT=Math.log(MAX_INT);function Integer(v,radix){if(typeof v==="undefined")return Integer[0];if(typeof radix!=="undefined")return+radix===10?parseValue(v):parseBase(v,radix);return parseValue(v)}function BigInteger(value,sign){this.value=value;this.sign=sign;this.isSmall=false}BigInteger.prototype=Object.create(Integer.prototype);function SmallInteger(value){this.value=value;this.sign=value<0;this.isSmall=true}SmallInteger.prototype=Object.create(Integer.prototype);function isPrecise(n){return-MAX_INT<n&&n<MAX_INT}function smallToArray(n){if(n<1e7)return[n];if(n<1e14)return[n%1e7,Math.floor(n/1e7)];return[n%1e7,Math.floor(n/1e7)%1e7,Math.floor(n/1e14)]}function arrayToSmall(arr){trim(arr);var length=arr.length;if(length<4&&compareAbs(arr,MAX_INT_ARR)<0){switch(length){case 0:return 0;case 1:return arr[0];case 2:return arr[0]+arr[1]*BASE;default:return arr[0]+(arr[1]+arr[2]*BASE)*BASE}}return arr}function trim(v){var i=v.length;while(v[--i]===0);v.length=i+1}function createArray(length){var x=new Array(length);var i=-1;while(++i<length){x[i]=0}return x}function truncate(n){if(n>0)return Math.floor(n);return Math.ceil(n)}function add(a,b){var l_a=a.length,l_b=b.length,r=new Array(l_a),carry=0,base=BASE,sum,i;for(i=0;i<l_b;i++){sum=a[i]+b[i]+carry;carry=sum>=base?1:0;r[i]=sum-carry*base}while(i<l_a){sum=a[i]+carry;carry=sum===base?1:0;r[i++]=sum-carry*base}if(carry>0)r.push(carry);return r}function addAny(a,b){if(a.length>=b.length)return add(a,b);return add(b,a)}function addSmall(a,carry){var l=a.length,r=new Array(l),base=BASE,sum,i;for(i=0;i<l;i++){sum=a[i]-base+carry;carry=Math.floor(sum/base);r[i]=sum-carry*base;carry+=1}while(carry>0){r[i++]=carry%base;carry=Math.floor(carry/base)}return r}BigInteger.prototype.add=function(v){var n=parseValue(v);if(this.sign!==n.sign){return this.subtract(n.negate())}var a=this.value,b=n.value;if(n.isSmall){return new BigInteger(addSmall(a,Math.abs(b)),this.sign)}return new BigInteger(addAny(a,b),this.sign)};BigInteger.prototype.plus=BigInteger.prototype.add;SmallInteger.prototype.add=function(v){var n=parseValue(v);var a=this.value;if(a<0!==n.sign){return this.subtract(n.negate())}var b=n.value;if(n.isSmall){if(isPrecise(a+b))return new SmallInteger(a+b);b=smallToArray(Math.abs(b))}return new BigInteger(addSmall(b,Math.abs(a)),a<0)};SmallInteger.prototype.plus=SmallInteger.prototype.add;function subtract(a,b){var a_l=a.length,b_l=b.length,r=new Array(a_l),borrow=0,base=BASE,i,difference;for(i=0;i<b_l;i++){difference=a[i]-borrow-b[i];if(difference<0){difference+=base;borrow=1}else borrow=0;r[i]=difference}for(i=b_l;i<a_l;i++){difference=a[i]-borrow;if(difference<0)difference+=base;else{r[i++]=difference;break}r[i]=difference}for(;i<a_l;i++){r[i]=a[i]}trim(r);return r}function subtractAny(a,b,sign){var value;if(compareAbs(a,b)>=0){value=subtract(a,b)}else{value=subtract(b,a);sign=!sign}value=arrayToSmall(value);if(typeof value==="number"){if(sign)value=-value;return new SmallInteger(value)}return new BigInteger(value,sign)}function subtractSmall(a,b,sign){var l=a.length,r=new Array(l),carry=-b,base=BASE,i,difference;for(i=0;i<l;i++){difference=a[i]+carry;carry=Math.floor(difference/base);difference%=base;r[i]=difference<0?difference+base:difference}r=arrayToSmall(r);if(typeof r==="number"){if(sign)r=-r;return new SmallInteger(r)}return new BigInteger(r,sign)}BigInteger.prototype.subtract=function(v){var n=parseValue(v);if(this.sign!==n.sign){return this.add(n.negate())}var a=this.value,b=n.value;if(n.isSmall)return subtractSmall(a,Math.abs(b),this.sign);return subtractAny(a,b,this.sign)};BigInteger.prototype.minus=BigInteger.prototype.subtract;SmallInteger.prototype.subtract=function(v){var n=parseValue(v);var a=this.value;if(a<0!==n.sign){return this.add(n.negate())}var b=n.value;if(n.isSmall){return new SmallInteger(a-b)}return subtractSmall(b,Math.abs(a),a>=0)};SmallInteger.prototype.minus=SmallInteger.prototype.subtract;BigInteger.prototype.negate=function(){return new BigInteger(this.value,!this.sign)};SmallInteger.prototype.negate=function(){var sign=this.sign;var small=new SmallInteger(-this.value);small.sign=!sign;return small};BigInteger.prototype.abs=function(){return new BigInteger(this.value,false)};SmallInteger.prototype.abs=function(){return new SmallInteger(Math.abs(this.value))};function multiplyLong(a,b){var a_l=a.length,b_l=b.length,l=a_l+b_l,r=createArray(l),base=BASE,product,carry,i,a_i,b_j;for(i=0;i<a_l;++i){a_i=a[i];for(var j=0;j<b_l;++j){b_j=b[j];product=a_i*b_j+r[i+j];carry=Math.floor(product/base);r[i+j]=product-carry*base;r[i+j+1]+=carry}}trim(r);return r}function multiplySmall(a,b){var l=a.length,r=new Array(l),base=BASE,carry=0,product,i;for(i=0;i<l;i++){product=a[i]*b+carry;carry=Math.floor(product/base);r[i]=product-carry*base}while(carry>0){r[i++]=carry%base;carry=Math.floor(carry/base)}return r}function shiftLeft(x,n){var r=[];while(n-- >0)r.push(0);return r.concat(x)}function multiplyKaratsuba(x,y){var n=Math.max(x.length,y.length);if(n<=30)return multiplyLong(x,y);n=Math.ceil(n/2);var b=x.slice(n),a=x.slice(0,n),d=y.slice(n),c=y.slice(0,n);var ac=multiplyKaratsuba(a,c),bd=multiplyKaratsuba(b,d),abcd=multiplyKaratsuba(addAny(a,b),addAny(c,d));var product=addAny(addAny(ac,shiftLeft(subtract(subtract(abcd,ac),bd),n)),shiftLeft(bd,2*n));trim(product);return product}function useKaratsuba(l1,l2){return-.012*l1-.012*l2+15e-6*l1*l2>0}BigInteger.prototype.multiply=function(v){var n=parseValue(v),a=this.value,b=n.value,sign=this.sign!==n.sign,abs;if(n.isSmall){if(b===0)return Integer[0];if(b===1)return this;if(b===-1)return this.negate();abs=Math.abs(b);if(abs<BASE){return new BigInteger(multiplySmall(a,abs),sign)}b=smallToArray(abs)}if(useKaratsuba(a.length,b.length))return new BigInteger(multiplyKaratsuba(a,b),sign);return new BigInteger(multiplyLong(a,b),sign)};BigInteger.prototype.times=BigInteger.prototype.multiply;function multiplySmallAndArray(a,b,sign){if(a<BASE){return new BigInteger(multiplySmall(b,a),sign)}return new BigInteger(multiplyLong(b,smallToArray(a)),sign)}SmallInteger.prototype._multiplyBySmall=function(a){if(isPrecise(a.value*this.value)){return new SmallInteger(a.value*this.value)}return multiplySmallAndArray(Math.abs(a.value),smallToArray(Math.abs(this.value)),this.sign!==a.sign)};BigInteger.prototype._multiplyBySmall=function(a){if(a.value===0)return Integer[0];if(a.value===1)return this;if(a.value===-1)return this.negate();return multiplySmallAndArray(Math.abs(a.value),this.value,this.sign!==a.sign)};SmallInteger.prototype.multiply=function(v){return parseValue(v)._multiplyBySmall(this)};SmallInteger.prototype.times=SmallInteger.prototype.multiply;function square(a){var l=a.length,r=createArray(l+l),base=BASE,product,carry,i,a_i,a_j;for(i=0;i<l;i++){a_i=a[i];for(var j=0;j<l;j++){a_j=a[j];product=a_i*a_j+r[i+j];carry=Math.floor(product/base);r[i+j]=product-carry*base;r[i+j+1]+=carry}}trim(r);return r}BigInteger.prototype.square=function(){return new BigInteger(square(this.value),false)};SmallInteger.prototype.square=function(){var value=this.value*this.value;if(isPrecise(value))return new SmallInteger(value);return new BigInteger(square(smallToArray(Math.abs(this.value))),false)};function divMod1(a,b){var a_l=a.length,b_l=b.length,base=BASE,result=createArray(b.length),divisorMostSignificantDigit=b[b_l-1],lambda=Math.ceil(base/(2*divisorMostSignificantDigit)),remainder=multiplySmall(a,lambda),divisor=multiplySmall(b,lambda),quotientDigit,shift,carry,borrow,i,l,q;if(remainder.length<=a_l)remainder.push(0);divisor.push(0);divisorMostSignificantDigit=divisor[b_l-1];for(shift=a_l-b_l;shift>=0;shift--){quotientDigit=base-1;if(remainder[shift+b_l]!==divisorMostSignificantDigit){quotientDigit=Math.floor((remainder[shift+b_l]*base+remainder[shift+b_l-1])/divisorMostSignificantDigit)}carry=0;borrow=0;l=divisor.length;for(i=0;i<l;i++){carry+=quotientDigit*divisor[i];q=Math.floor(carry/base);borrow+=remainder[shift+i]-(carry-q*base);carry=q;if(borrow<0){remainder[shift+i]=borrow+base;borrow=-1}else{remainder[shift+i]=borrow;borrow=0}}while(borrow!==0){quotientDigit-=1;carry=0;for(i=0;i<l;i++){carry+=remainder[shift+i]-base+divisor[i];if(carry<0){remainder[shift+i]=carry+base;carry=0}else{remainder[shift+i]=carry;carry=1}}borrow+=carry}result[shift]=quotientDigit}remainder=divModSmall(remainder,lambda)[0];return[arrayToSmall(result),arrayToSmall(remainder)]}function divMod2(a,b){var a_l=a.length,b_l=b.length,result=[],part=[],base=BASE,guess,xlen,highx,highy,check;while(a_l){part.unshift(a[--a_l]);trim(part);if(compareAbs(part,b)<0){result.push(0);continue}xlen=part.length;highx=part[xlen-1]*base+part[xlen-2];highy=b[b_l-1]*base+b[b_l-2];if(xlen>b_l){highx=(highx+1)*base}guess=Math.ceil(highx/highy);do{check=multiplySmall(b,guess);if(compareAbs(check,part)<=0)break;guess--}while(guess);result.push(guess);part=subtract(part,check)}result.reverse();return[arrayToSmall(result),arrayToSmall(part)]}function divModSmall(value,lambda){var length=value.length,quotient=createArray(length),base=BASE,i,q,remainder,divisor;remainder=0;for(i=length-1;i>=0;--i){divisor=remainder*base+value[i];q=truncate(divisor/lambda);remainder=divisor-q*lambda;quotient[i]=q|0}return[quotient,remainder|0]}function divModAny(self,v){var value,n=parseValue(v);var a=self.value,b=n.value;var quotient;if(b===0)throw new Error("Cannot divide by zero");if(self.isSmall){if(n.isSmall){return[new SmallInteger(truncate(a/b)),new SmallInteger(a%b)]}return[Integer[0],self]}if(n.isSmall){if(b===1)return[self,Integer[0]];if(b==-1)return[self.negate(),Integer[0]];var abs=Math.abs(b);if(abs<BASE){value=divModSmall(a,abs);quotient=arrayToSmall(value[0]);var remainder=value[1];if(self.sign)remainder=-remainder;if(typeof quotient==="number"){if(self.sign!==n.sign)quotient=-quotient;return[new SmallInteger(quotient),new SmallInteger(remainder)]}return[new BigInteger(quotient,self.sign!==n.sign),new SmallInteger(remainder)]}b=smallToArray(abs)}var comparison=compareAbs(a,b);if(comparison===-1)return[Integer[0],self];if(comparison===0)return[Integer[self.sign===n.sign?1:-1],Integer[0]];if(a.length+b.length<=200)value=divMod1(a,b);else value=divMod2(a,b);quotient=value[0];var qSign=self.sign!==n.sign,mod=value[1],mSign=self.sign;if(typeof quotient==="number"){if(qSign)quotient=-quotient;quotient=new SmallInteger(quotient)}else quotient=new BigInteger(quotient,qSign);if(typeof mod==="number"){if(mSign)mod=-mod;mod=new SmallInteger(mod)}else mod=new BigInteger(mod,mSign);return[quotient,mod]}BigInteger.prototype.divmod=function(v){var result=divModAny(this,v);return{quotient:result[0],remainder:result[1]}};SmallInteger.prototype.divmod=BigInteger.prototype.divmod;BigInteger.prototype.divide=function(v){return divModAny(this,v)[0]};SmallInteger.prototype.over=SmallInteger.prototype.divide=BigInteger.prototype.over=BigInteger.prototype.divide;BigInteger.prototype.mod=function(v){return divModAny(this,v)[1]};SmallInteger.prototype.remainder=SmallInteger.prototype.mod=BigInteger.prototype.remainder=BigInteger.prototype.mod;BigInteger.prototype.pow=function(v){var n=parseValue(v),a=this.value,b=n.value,value,x,y;if(b===0)return Integer[1];if(a===0)return Integer[0];if(a===1)return Integer[1];if(a===-1)return n.isEven()?Integer[1]:Integer[-1];if(n.sign){return Integer[0]}if(!n.isSmall)throw new Error("The exponent "+n.toString()+" is too large.");if(this.isSmall){if(isPrecise(value=Math.pow(a,b)))return new SmallInteger(truncate(value))}x=this;y=Integer[1];while(true){if(b&1===1){y=y.times(x);--b}if(b===0)break;b/=2;x=x.square()}return y};SmallInteger.prototype.pow=BigInteger.prototype.pow;BigInteger.prototype.modPow=function(exp,mod){exp=parseValue(exp);mod=parseValue(mod);if(mod.isZero())throw new Error("Cannot take modPow with modulus 0");var r=Integer[1],base=this.mod(mod);while(exp.isPositive()){if(base.isZero())return Integer[0];if(exp.isOdd())r=r.multiply(base).mod(mod);exp=exp.divide(2);base=base.square().mod(mod)}return r};SmallInteger.prototype.modPow=BigInteger.prototype.modPow;function compareAbs(a,b){if(a.length!==b.length){return a.length>b.length?1:-1}for(var i=a.length-1;i>=0;i--){if(a[i]!==b[i])return a[i]>b[i]?1:-1}return 0}BigInteger.prototype.compareAbs=function(v){var n=parseValue(v),a=this.value,b=n.value;if(n.isSmall)return 1;return compareAbs(a,b)};SmallInteger.prototype.compareAbs=function(v){var n=parseValue(v),a=Math.abs(this.value),b=n.value;if(n.isSmall){b=Math.abs(b);return a===b?0:a>b?1:-1}return-1};BigInteger.prototype.compare=function(v){if(v===Infinity){return-1}if(v===-Infinity){return 1}var n=parseValue(v),a=this.value,b=n.value;if(this.sign!==n.sign){return n.sign?1:-1}if(n.isSmall){return this.sign?-1:1}return compareAbs(a,b)*(this.sign?-1:1)};BigInteger.prototype.compareTo=BigInteger.prototype.compare;SmallInteger.prototype.compare=function(v){if(v===Infinity){return-1}if(v===-Infinity){return 1}var n=parseValue(v),a=this.value,b=n.value;if(n.isSmall){return a==b?0:a>b?1:-1}if(a<0!==n.sign){return a<0?-1:1}return a<0?1:-1};SmallInteger.prototype.compareTo=SmallInteger.prototype.compare;BigInteger.prototype.equals=function(v){return this.compare(v)===0};SmallInteger.prototype.eq=SmallInteger.prototype.equals=BigInteger.prototype.eq=BigInteger.prototype.equals;BigInteger.prototype.notEquals=function(v){return this.compare(v)!==0};SmallInteger.prototype.neq=SmallInteger.prototype.notEquals=BigInteger.prototype.neq=BigInteger.prototype.notEquals;BigInteger.prototype.greater=function(v){return this.compare(v)>0};SmallInteger.prototype.gt=SmallInteger.prototype.greater=BigInteger.prototype.gt=BigInteger.prototype.greater;BigInteger.prototype.lesser=function(v){return this.compare(v)<0};SmallInteger.prototype.lt=SmallInteger.prototype.lesser=BigInteger.prototype.lt=BigInteger.prototype.lesser;BigInteger.prototype.greaterOrEquals=function(v){return this.compare(v)>=0};SmallInteger.prototype.geq=SmallInteger.prototype.greaterOrEquals=BigInteger.prototype.geq=BigInteger.prototype.greaterOrEquals;BigInteger.prototype.lesserOrEquals=function(v){return this.compare(v)<=0};SmallInteger.prototype.leq=SmallInteger.prototype.lesserOrEquals=BigInteger.prototype.leq=BigInteger.prototype.lesserOrEquals;BigInteger.prototype.isEven=function(){return(this.value[0]&1)===0};SmallInteger.prototype.isEven=function(){return(this.value&1)===0};BigInteger.prototype.isOdd=function(){return(this.value[0]&1)===1};SmallInteger.prototype.isOdd=function(){return(this.value&1)===1};BigInteger.prototype.isPositive=function(){return!this.sign};SmallInteger.prototype.isPositive=function(){return this.value>0};BigInteger.prototype.isNegative=function(){return this.sign};SmallInteger.prototype.isNegative=function(){return this.value<0};BigInteger.prototype.isUnit=function(){return false};SmallInteger.prototype.isUnit=function(){return Math.abs(this.value)===1};BigInteger.prototype.isZero=function(){return false};SmallInteger.prototype.isZero=function(){return this.value===0};BigInteger.prototype.isDivisibleBy=function(v){var n=parseValue(v);var value=n.value;if(value===0)return false;if(value===1)return true;if(value===2)return this.isEven();return this.mod(n).equals(Integer[0])};SmallInteger.prototype.isDivisibleBy=BigInteger.prototype.isDivisibleBy;function isBasicPrime(v){var n=v.abs();if(n.isUnit())return false;if(n.equals(2)||n.equals(3)||n.equals(5))return true;if(n.isEven()||n.isDivisibleBy(3)||n.isDivisibleBy(5))return false;if(n.lesser(25))return true}BigInteger.prototype.isPrime=function(){var isPrime=isBasicPrime(this);if(isPrime!==undefined)return isPrime;var n=this.abs(),nPrev=n.prev();var a=[2,3,5,7,11,13,17,19],b=nPrev,d,t,i,x;while(b.isEven())b=b.divide(2);for(i=0;i<a.length;i++){x=bigInt(a[i]).modPow(b,n);if(x.equals(Integer[1])||x.equals(nPrev))continue;for(t=true,d=b;t&&d.lesser(nPrev);d=d.multiply(2)){x=x.square().mod(n);if(x.equals(nPrev))t=false}if(t)return false}return true};SmallInteger.prototype.isPrime=BigInteger.prototype.isPrime;BigInteger.prototype.isProbablePrime=function(iterations){var isPrime=isBasicPrime(this);if(isPrime!==undefined)return isPrime;var n=this.abs();var t=iterations===undefined?5:iterations;for(var i=0;i<t;i++){var a=bigInt.randBetween(2,n.minus(2));if(!a.modPow(n.prev(),n).isUnit())return false}return true};SmallInteger.prototype.isProbablePrime=BigInteger.prototype.isProbablePrime;BigInteger.prototype.modInv=function(n){var t=bigInt.zero,newT=bigInt.one,r=parseValue(n),newR=this.abs(),q,lastT,lastR;while(!newR.equals(bigInt.zero)){q=r.divide(newR);lastT=t;lastR=r;t=newT;r=newR;newT=lastT.subtract(q.multiply(newT));newR=lastR.subtract(q.multiply(newR))}if(!r.equals(1))throw new Error(this.toString()+" and "+n.toString()+" are not co-prime");if(t.compare(0)===-1){t=t.add(n)}if(this.isNegative()){return t.negate()}return t};SmallInteger.prototype.modInv=BigInteger.prototype.modInv;BigInteger.prototype.next=function(){var value=this.value;if(this.sign){return subtractSmall(value,1,this.sign)}return new BigInteger(addSmall(value,1),this.sign)};SmallInteger.prototype.next=function(){var value=this.value;if(value+1<MAX_INT)return new SmallInteger(value+1);return new BigInteger(MAX_INT_ARR,false)};BigInteger.prototype.prev=function(){var value=this.value;if(this.sign){return new BigInteger(addSmall(value,1),true)}return subtractSmall(value,1,this.sign)};SmallInteger.prototype.prev=function(){var value=this.value;if(value-1>-MAX_INT)return new SmallInteger(value-1);return new BigInteger(MAX_INT_ARR,true)};var powersOfTwo=[1];while(2*powersOfTwo[powersOfTwo.length-1]<=BASE)powersOfTwo.push(2*powersOfTwo[powersOfTwo.length-1]);var powers2Length=powersOfTwo.length,highestPower2=powersOfTwo[powers2Length-1];function shift_isSmall(n){return(typeof n==="number"||typeof n==="string")&&+Math.abs(n)<=BASE||n instanceof BigInteger&&n.value.length<=1}BigInteger.prototype.shiftLeft=function(n){if(!shift_isSmall(n)){throw new Error(String(n)+" is too large for shifting.")}n=+n;if(n<0)return this.shiftRight(-n);var result=this;while(n>=powers2Length){result=result.multiply(highestPower2);n-=powers2Length-1}return result.multiply(powersOfTwo[n])};SmallInteger.prototype.shiftLeft=BigInteger.prototype.shiftLeft;BigInteger.prototype.shiftRight=function(n){var remQuo;if(!shift_isSmall(n)){throw new Error(String(n)+" is too large for shifting.")}n=+n;if(n<0)return this.shiftLeft(-n);var result=this;while(n>=powers2Length){if(result.isZero())return result;remQuo=divModAny(result,highestPower2);result=remQuo[1].isNegative()?remQuo[0].prev():remQuo[0];n-=powers2Length-1}remQuo=divModAny(result,powersOfTwo[n]);return remQuo[1].isNegative()?remQuo[0].prev():remQuo[0]};SmallInteger.prototype.shiftRight=BigInteger.prototype.shiftRight;function bitwise(x,y,fn){y=parseValue(y);var xSign=x.isNegative(),ySign=y.isNegative();var xRem=xSign?x.not():x,yRem=ySign?y.not():y;var xDigit=0,yDigit=0;var xDivMod=null,yDivMod=null;var result=[];while(!xRem.isZero()||!yRem.isZero()){xDivMod=divModAny(xRem,highestPower2);xDigit=xDivMod[1].toJSNumber();if(xSign){xDigit=highestPower2-1-xDigit}yDivMod=divModAny(yRem,highestPower2);yDigit=yDivMod[1].toJSNumber();if(ySign){yDigit=highestPower2-1-yDigit}xRem=xDivMod[0];yRem=yDivMod[0];result.push(fn(xDigit,yDigit))}var sum=fn(xSign?1:0,ySign?1:0)!==0?bigInt(-1):bigInt(0);for(var i=result.length-1;i>=0;i-=1){sum=sum.multiply(highestPower2).add(bigInt(result[i]))}return sum}BigInteger.prototype.not=function(){return this.negate().prev()};SmallInteger.prototype.not=BigInteger.prototype.not;BigInteger.prototype.and=function(n){return bitwise(this,n,function(a,b){return a&b})};SmallInteger.prototype.and=BigInteger.prototype.and;BigInteger.prototype.or=function(n){return bitwise(this,n,function(a,b){return a|b})};SmallInteger.prototype.or=BigInteger.prototype.or;BigInteger.prototype.xor=function(n){return bitwise(this,n,function(a,b){return a^b})};SmallInteger.prototype.xor=BigInteger.prototype.xor;var LOBMASK_I=1<<30,LOBMASK_BI=(BASE&-BASE)*(BASE&-BASE)|LOBMASK_I;function roughLOB(n){var v=n.value,x=typeof v==="number"?v|LOBMASK_I:v[0]+v[1]*BASE|LOBMASK_BI;return x&-x}function integerLogarithm(value,base){if(base.compareTo(value)<=0){var tmp=integerLogarithm(value,base.square(base));var p=tmp.p;var e=tmp.e;var t=p.multiply(base);return t.compareTo(value)<=0?{p:t,e:e*2+1}:{p:p,e:e*2}}return{p:bigInt(1),e:0}}BigInteger.prototype.bitLength=function(){var n=this;if(n.compareTo(bigInt(0))<0){n=n.negate().subtract(bigInt(1))}if(n.compareTo(bigInt(0))===0){return bigInt(0)}return bigInt(integerLogarithm(n,bigInt(2)).e).add(bigInt(1))};SmallInteger.prototype.bitLength=BigInteger.prototype.bitLength;function max(a,b){a=parseValue(a);b=parseValue(b);return a.greater(b)?a:b}function min(a,b){a=parseValue(a);b=parseValue(b);return a.lesser(b)?a:b}function gcd(a,b){a=parseValue(a).abs();b=parseValue(b).abs();if(a.equals(b))return a;if(a.isZero())return b;if(b.isZero())return a;var c=Integer[1],d,t;while(a.isEven()&&b.isEven()){d=Math.min(roughLOB(a),roughLOB(b));a=a.divide(d);b=b.divide(d);c=c.multiply(d)}while(a.isEven()){a=a.divide(roughLOB(a))}do{while(b.isEven()){b=b.divide(roughLOB(b))}if(a.greater(b)){t=b;b=a;a=t}b=b.subtract(a)}while(!b.isZero());return c.isUnit()?a:a.multiply(c)}function lcm(a,b){a=parseValue(a).abs();b=parseValue(b).abs();return a.divide(gcd(a,b)).multiply(b)}function randBetween(a,b){a=parseValue(a);b=parseValue(b);var low=min(a,b),high=max(a,b);var range=high.subtract(low).add(1);if(range.isSmall)return low.add(Math.floor(Math.random()*range));var length=range.value.length-1;var result=[],restricted=true;for(var i=length;i>=0;i--){var top=restricted?range.value[i]:BASE;var digit=truncate(Math.random()*top);result.unshift(digit);if(digit<top)restricted=false}result=arrayToSmall(result);return low.add(typeof result==="number"?new SmallInteger(result):new BigInteger(result,false))}var parseBase=function(text,base){var length=text.length;var i;var absBase=Math.abs(base);for(var i=0;i<length;i++){var c=text[i].toLowerCase();if(c==="-")continue;if(/[a-z0-9]/.test(c)){if(/[0-9]/.test(c)&&+c>=absBase){if(c==="1"&&absBase===1)continue;throw new Error(c+" is not a valid digit in base "+base+".")}else if(c.charCodeAt(0)-87>=absBase){throw new Error(c+" is not a valid digit in base "+base+".")}}}if(2<=base&&base<=36){if(length<=LOG_MAX_INT/Math.log(base)){var result=parseInt(text,base);if(isNaN(result)){throw new Error(c+" is not a valid digit in base "+base+".")}return new SmallInteger(parseInt(text,base))}}base=parseValue(base);var digits=[];var isNegative=text[0]==="-";for(i=isNegative?1:0;i<text.length;i++){var c=text[i].toLowerCase(),charCode=c.charCodeAt(0);if(48<=charCode&&charCode<=57)digits.push(parseValue(c));else if(97<=charCode&&charCode<=122)digits.push(parseValue(c.charCodeAt(0)-87));else if(c==="<"){var start=i;do{i++}while(text[i]!==">");digits.push(parseValue(text.slice(start+1,i)))}else throw new Error(c+" is not a valid character")}return parseBaseFromArray(digits,base,isNegative)};function parseBaseFromArray(digits,base,isNegative){var val=Integer[0],pow=Integer[1],i;for(i=digits.length-1;i>=0;i--){val=val.add(digits[i].times(pow));pow=pow.times(base)}return isNegative?val.negate():val}function stringify(digit){if(digit<=35){return"0123456789abcdefghijklmnopqrstuvwxyz".charAt(digit)}return"<"+digit+">"}function toBase(n,base){base=bigInt(base);if(base.isZero()){if(n.isZero())return{value:[0],isNegative:false};throw new Error("Cannot convert nonzero numbers to base 0.")}if(base.equals(-1)){if(n.isZero())return{value:[0],isNegative:false};if(n.isNegative())return{value:[].concat.apply([],Array.apply(null,Array(-n)).map(Array.prototype.valueOf,[1,0])),isNegative:false};var arr=Array.apply(null,Array(+n-1)).map(Array.prototype.valueOf,[0,1]);arr.unshift([1]);return{value:[].concat.apply([],arr),isNegative:false}}var neg=false;if(n.isNegative()&&base.isPositive()){neg=true;n=n.abs()}if(base.equals(1)){if(n.isZero())return{value:[0],isNegative:false};return{value:Array.apply(null,Array(+n)).map(Number.prototype.valueOf,1),isNegative:neg}}var out=[];var left=n,divmod;while(left.isNegative()||left.compareAbs(base)>=0){divmod=left.divmod(base);left=divmod.quotient;var digit=divmod.remainder;if(digit.isNegative()){digit=base.minus(digit).abs();left=left.next()}out.push(digit.toJSNumber())}out.push(left.toJSNumber());return{value:out.reverse(),isNegative:neg}}function toBaseString(n,base){var arr=toBase(n,base);return(arr.isNegative?"-":"")+arr.value.map(stringify).join("")}BigInteger.prototype.toArray=function(radix){return toBase(this,radix)};SmallInteger.prototype.toArray=function(radix){return toBase(this,radix)};BigInteger.prototype.toString=function(radix){if(radix===undefined)radix=10;if(radix!==10)return toBaseString(this,radix);var v=this.value,l=v.length,str=String(v[--l]),zeros="0000000",digit;while(--l>=0){digit=String(v[l]);str+=zeros.slice(digit.length)+digit}var sign=this.sign?"-":"";return sign+str};SmallInteger.prototype.toString=function(radix){if(radix===undefined)radix=10;if(radix!=10)return toBaseString(this,radix);return String(this.value)};BigInteger.prototype.toJSON=SmallInteger.prototype.toJSON=function(){return this.toString()};BigInteger.prototype.valueOf=function(){return parseInt(this.toString(),10)};BigInteger.prototype.toJSNumber=BigInteger.prototype.valueOf;SmallInteger.prototype.valueOf=function(){return this.value};SmallInteger.prototype.toJSNumber=SmallInteger.prototype.valueOf;function parseStringValue(v){if(isPrecise(+v)){var x=+v;if(x===truncate(x))return new SmallInteger(x);throw new Error("Invalid integer: "+v)}var sign=v[0]==="-";if(sign)v=v.slice(1);var split=v.split(/e/i);if(split.length>2)throw new Error("Invalid integer: "+split.join("e"));if(split.length===2){var exp=split[1];if(exp[0]==="+")exp=exp.slice(1);exp=+exp;if(exp!==truncate(exp)||!isPrecise(exp))throw new Error("Invalid integer: "+exp+" is not a valid exponent.");var text=split[0];var decimalPlace=text.indexOf(".");if(decimalPlace>=0){exp-=text.length-decimalPlace-1;text=text.slice(0,decimalPlace)+text.slice(decimalPlace+1)}if(exp<0)throw new Error("Cannot include negative exponent part for integers");text+=new Array(exp+1).join("0");v=text}var isValid=/^([0-9][0-9]*)$/.test(v);if(!isValid)throw new Error("Invalid integer: "+v);var r=[],max=v.length,l=LOG_BASE,min=max-l;while(max>0){r.push(+v.slice(min,max));min-=l;if(min<0)min=0;max-=l}trim(r);return new BigInteger(r,sign)}function parseNumberValue(v){if(isPrecise(v)){if(v!==truncate(v))throw new Error(v+" is not an integer.");return new SmallInteger(v)}return parseStringValue(v.toString())}function parseValue(v){if(typeof v==="number"){return parseNumberValue(v)}if(typeof v==="string"){return parseStringValue(v)}return v}for(var i=0;i<1e3;i++){Integer[i]=new SmallInteger(i);if(i>0)Integer[-i]=new SmallInteger(-i)}Integer.one=Integer[1];Integer.zero=Integer[0];Integer.minusOne=Integer[-1];Integer.max=max;Integer.min=min;Integer.gcd=gcd;Integer.lcm=lcm;Integer.isInstance=function(x){return x instanceof BigInteger||x instanceof SmallInteger};Integer.randBetween=randBetween;Integer.fromArray=function(digits,base,isNegative){return parseBaseFromArray(digits.map(parseValue),parseValue(base||10),isNegative)};return Integer}();if(typeof module!=="undefined"&&module.hasOwnProperty("exports")){module.exports=bigInt}if(typeof define==="function"&&define.amd){define("big-integer",[],function(){return bigInt})}
/** ..\Modules\aras.innovator.core.MainWindow\ArasMainWindowInfo.js **/
var ArasMainWindowInfo = (function() {
	function ArasMainWindowInfo(aras) {
		this.aras = aras;
	}
	Object.defineProperty(ArasMainWindowInfo.prototype, 'getIdentityListResult', {
		get: function() {
			return this.getSoapResult('getIdentityList', '/*/*/*/GetIdentityListResult/*');
		},
		enumerable: true,
		configurable: true
	});
	Object.defineProperty(ArasMainWindowInfo.prototype, 'getUserResult', {
		get: function() {
			return this.getSoapResult('getUser', '/*/*/*/GetUserResult/*');
		},
		enumerable: true,
		configurable: true
	});
	Object.defineProperty(ArasMainWindowInfo.prototype, 'getLanguageResult', {
		get: function() {
			return this.getSoapResult('getLanguage', '/*/*/*/GetLanguageResult/*');
		},
		enumerable: true,
		configurable: true
	});
	Object.defineProperty(ArasMainWindowInfo.prototype, 'isFeatureTreeExpiredResult', {
		get: function() {
			return this.provider
				.getResultNode('isFeatureTreeExpired')
				.selectSingleNode('/*/*/*/IsFeatureTreeExpiredResult/Result')
				.text;
		},
		enumerable: true,
		configurable: true
	});
	Object.defineProperty(ArasMainWindowInfo.prototype, 'getCheckUpdateInfoResult', {
		get: function() {
			return this.getSoapResult('getCheckUpdateInfo', '/*/*/*/GetCheckUpdateInfoResult/*');
		},
		enumerable: true,
		configurable: true
	});
	Object.defineProperty(ArasMainWindowInfo.prototype, 'IsSSVCLicenseOk', {
		get: function() {
			return this.provider
				.getResultNode('IsSSVCLicenseOk')
				.selectSingleNode('/*/*/*/IsSSVCLicenseOk/Result')
				.text === 'True';
		},
		enumerable: true,
		configurable: true
	});
	Object.defineProperty(ArasMainWindowInfo.prototype, 'MessageCheckInterval', {
		get: function() {
			return this.provider
				.getResultNode('MessageCheckInterval')
				.selectSingleNode('/*/*/*/MessageCheckInterval/Result')
				.text;
		},
		enumerable: true,
		configurable: true
	});
	Object.defineProperty(ArasMainWindowInfo.prototype, 'SSVC_Preferences', {
		get: function() {
			return this.getSoapResult('SSVC_Preferences', '/*/*/*/SSVC_Preferences/*');
		},
		enumerable: true,
		configurable: true
	});
	Object.defineProperty(ArasMainWindowInfo.prototype, 'Core_GlobalLayout', {
		get: function() {
			return this.getSoapResult('CoreGlobalLayoutPreference', '/*/*/*/Core_GlobalLayout/*');
		},
		enumerable: true,
		configurable: true
	});
	Object.defineProperty(ArasMainWindowInfo.prototype, 'GetAllMetadataDates', {
		get: function() {
			var soap = this.getSoapResult('GetMetadataInfoDates', '/*/*/*/GetMetadataInfoDates');
			return soap.results.selectSingleNode('GetMetadataInfoDates');
		},
		enumerable: true,
		configurable: true
	});
	Object.defineProperty(ArasMainWindowInfo.prototype, 'SearchCountMode', {
		get: function() {
			return this.provider
				.getResultNode('GetSearchCountMode')
				.selectSingleNode('/*/*/*/SearchCountMode/Result')
				.text;
		},
		enumerable: true,
		configurable: true
	});
	Object.defineProperty(ArasMainWindowInfo.prototype, 'Core_SearchCountModeException', {
		get: function() {
			return this.provider
				.getResultNode('GetSearchCountModeExceptions')
				.selectSingleNode('/*/*/*/Core_SearchCountModeException/Result')
				.text
				.split(',');
		},
		enumerable: true,
		configurable: true
	});
	Object.defineProperty(ArasMainWindowInfo.prototype, 'ES_Settings', {
		get: function() {
			return this.getSoapResult('GetEsSettings', '/*/*/*/ES_Settings/*');
		},
		enumerable: true,
		configurable: true
	});
	ArasMainWindowInfo.prototype.setProvider = function(provider) {
		this.provider = provider;
	};
	ArasMainWindowInfo.prototype.getSoapResult = function(queryType, xpath) {
		if (this.provider === null) {
			throw new Error('Invalid operation. Set provider before.');
		}
		var resultNode = this.provider.getResultNode(queryType);
		var node = resultNode.selectSingleNode(xpath);
		return new SOAPResults(this.aras, node.xml);
	};
	return ArasMainWindowInfo;
}());

/** ..\Modules\aras.innovator.core.MainWindow\AsyncCachedMainWindowInfoProvider.js **/
var AsyncCachedMainWindowInfoProvider = (function() {
	function AsyncCachedMainWindowInfoProvider() {
	}
	AsyncCachedMainWindowInfoProvider.prototype.getResultNode = function(queryType) {
		if (!this.cachedResult) {
			throw new Error('Invalid operation. Call fetch() before.');
		}
		return this.cachedResult;
	};
	AsyncCachedMainWindowInfoProvider.prototype.fetch = function() {
		var _this = this;
		var soapConfig = {
			method: 'ApplyItem',
			async: true
		};
		return ArasModules
			.soap('<Item type=\'Method\' action=\'GetArasMainWindowInfo\'><query_type>all</query_type></Item>', soapConfig)
			.then(function(x) {
				_this.cachedResult = x;
				return _this;
			});
	};
	return AsyncCachedMainWindowInfoProvider;
}());

/** ..\Modules\aras.innovator.core.MainWindow\SyncMainWindowInfoProvider.js **/
var SyncMainWindowInfoProvider = (function() {
	function SyncMainWindowInfoProvider() {
	}
	SyncMainWindowInfoProvider.prototype.getResultNode = function(queryType) {
		var soapResult = aras.soapSend('ApplyMethod', '<Item type=\'Method\' action=\'GetArasMainWindowInfo\'><query_type>' + queryType + '</query_type></Item>');
		return soapResult.results;
	};
	return SyncMainWindowInfoProvider;
}());

/** Solution.js **/
function Solution(name, baseUrl) {
	/// <summary>
	///	 Solution class keeps all information about solution created.
	/// </summary>
	/// <summary locid="M:J#Aras.Client.JS.Solution.#ctor">
	/// This is summary for constructor.
	/// </summary>
	/// <param locid="M:J#Aras.Client.JS.Solution.#ctor" name="name" type="string" mayBeNull="false">
	///	 Name of solution.
	/// </param>
	this.baseUrl = baseUrl;
	this.name = name;
}

Solution.prototype.getBaseURL = function SolutionGetBaseURL() {
	/// <summary locid="M:J#Aras.Client.JS.Solution.getBaseURL">
	///  Get base URL of solution.
	/// </summary>
	/// <returns type="string">Returns base URL of solution.</returns>
	//check for not undefined instead of !this.baseUrl because this.baseUrl can be relative and '',
	//e.g., when Solution is created in the folder Client (in the base url)
	if (this.baseUrl !== undefined) {
		return this.baseUrl;
	}

	var s = window.location.href.replace(/(\/Client(?:\/X-salt=[^\/]*-X)?)(\/|$)(.*)/i, '$1');
	return s;
};
Solution.prototype.getServerBaseURL = function SolutionGetServerBaseURL() {
	/// <summary locid="M:J#Aras.Client.JS.Solution.getServerBaseURL">
	///  Get base server URL of solution.
	/// </summary>
	/// <returns type="string">Returns base URL of solution.</returns>
	var s = this.getBaseURL();
	return s.replace(/\/client(?:\/X-salt=[^\/]*-X)?$/i, '/Server/');
};
/*@cc_on
@if (@register_classes == 1)
Type.registerNamespace("Aras");
Type.registerNamespace("Aras.Client");
Type.registerNamespace("Aras.Client.JS");

Aras.Client.JS.Solution = Solution;
Aras.Client.JS.Solution.registerClass("Aras.Client.JS.Solution");
@end
@*/

/** XmlUtils.js **/
function XmlUtils() {}

// provide simple way to create xml documents without specifing needed attributes each time
XmlUtils.createDocument = function XmlUtilsCreateDocument() {
	return new XmlDocument();
};

// value returned as xpath function concat(), ie addition quotes aren't needed
XmlUtils.escapeXPathStringCriteria = function XmlUtilsEscapeXPathStringCriteria(str) {
	var res = str.replace(/'/g, '\',"\'",\'');
	if (res != str) {
		return 'concat(\'' + res + '\')';
	} else {
		return '\'' + res + '\'';
	}
};

/** ResourceManager.js **/
'use strict';

function ResourceManager(solution, resourceName, languageCodeOrAcceptLanguage) {
	/// <summary>
	///	 ResourceManager class provides access to culture-specific resources stored in xml.
	/// </summary>
	/// <remarks>
	///  The ResourceManager class looks up culture-specific resources and provides resource fallback when a localized resource does not exist.
	///  Using the methods of ResourceManager, a caller can access the resources for a particular culture using the getString and getFormatedString
	///  methods. By default, these methods return the resource for the culture determined by the cultural settings passed in constructor. If
	///  CultureInfo object is undefined or null, system settings are used (see Aras.Client.JS.CultureInfo.getCulture for more information).
	/// </remarks>
	/// <summary locid="M:J#Aras.Client.JS.ResourceManager.#ctor">
	///   Initializes a new instance of the ResourceManager class that looks up resources contained in file derived
	///   from the specified culture name using the given Solution.
	/// </summary>
	/// <param locid="M:J#Aras.Client.JS.ResourceManager.#ctor" name="solution" type="Aras.Client.JS.Solution" mayBeNull="false">
	///	 Solution object for which resources are needed.
	/// </param>
	/// <param locid="M:J#Aras.Client.JS.ResourceManager.#ctor" name="resourceName" type="string" mayBeNull="false">
	///	 The name of the resource file. For example, the resource name for the resource file "xml.fr/ui_resources.xml" is "ui_resources.xml".
	/// </param>
	/// <param locid="M:J#Aras.Client.JS.ResourceManager.#ctor" name="culture" mayBeNull="true" type="Aras.Client.JS.CultureInfo">
	///	 Specifies the CultureInfo object that represents the culture for which the resource is localized.
	///  If the resource is not localized for this culture, the CultureInfo is obtained using the system's CurrentCulture.
	/// </param>
	var _solution = solution;
	var _resourceName = resourceName;

	var _language = (languageCodeOrAcceptLanguage || undefined) && languageCodeOrAcceptLanguage.substr(0, 2);

	var _resourceConfigFileName = 'resource.config.xml';

	this.getResourceName = function ResourceManagerGetResourceName() {
		return _resourceName;
	};

	this.getConfigFileName = function ResourceManagerGetConfigFileName() {
		return _resourceConfigFileName;
	};

	this.getSolution = function ResourceManagerGetSolution() {
		return _solution;
	};

	this.getCultureName = function ResourceManagerGetCultureName() {
		return _language;
	};
}
/**
	variable ResourceManager$xmldocscache is stored in window.__staticVariablesStorage.
	And represents a cache of key-value pairs, where
	key is absolute url of resource and value - resource's xmlDocument.
**/
ResourceManager.prototype._getCache = function ResourceManagerGetCache() {
	var keyName = 'ResourceManager$xmldocscache';
	var res = window.__staticVariablesStorage[keyName];
	if (!res) {
		res = window.__staticVariablesStorage.setNewObject(keyName);
	}

	return res;
};

ResourceManager.prototype._getXmlDocument = function ResourceManagerGetXmlDocument(url) {
	var cache = this._getCache();

	var res = cache[url];
	if (res) {
		return res;
	}

	res = ArasModules.xml.parseFile(url);
	if (res.xml) {
		cache[url] = res;
		return res;
	}

	return null;
};

ResourceManager.prototype._getI18NResourcePath = function ResourceManagerGetI18NResourcePath(supportedCultureList) {
	var locale = this.getCultureName();
	var parentUrl = this.getSolution().getBaseURL();
	if (parentUrl[parentUrl.length - 1] != '/') {
		parentUrl += '/';
	}

	var defaultUrl = parentUrl + 'xml/' + this.getResourceName();
	var localizedUrl = parentUrl + 'xml' + (locale ? '.' + locale : '') + '/' + this.getResourceName();

	if (supportedCultureList !== null) {
		var culture = this._getCultureAttribute(supportedCultureList);
		if (culture == 'neutral') {
			return defaultUrl;
		}
	}

	return this._getLocalCulturePath(localizedUrl, defaultUrl);
};

ResourceManager.prototype._getCultureAttribute = function ResourceManagerGetCultureAttribute(supportedCultureList) {
	var locale = this.getCultureName();
	var defaultCultureKey = 'neutral';
	var localCulture = supportedCultureList.selectSingleNode('/*/*/resource[@culture=\'' + locale + '\']');
	if (!localCulture) {
		var defaultCulture = supportedCultureList.selectSingleNode('/*/*/resource[@culture=\'' + defaultCultureKey + '\']');
		return defaultCulture ? defaultCulture.getAttribute('culture') : '';
	}
	return localCulture.getAttribute('culture');
};

ResourceManager.prototype._getLocalCulturePath = function ResourceManagerGetLocalCulturePath(localizedUrl, defaultUrl) {
	var localizedResourceExists = this._getFileExist(localizedUrl);

	if (localizedResourceExists) {
		return localizedUrl;
	} else {
		return defaultUrl;
	}
};

ResourceManager.prototype._getFileExist = function ResourceManagerGetFileExist(url) {
	var cache = this._getCache();
	var cachePostfix = '_exist';
	var key = url + cachePostfix;
	var res = cache[key];
	if (res === undefined) {
		res = WebFile.Exists(url);
		cache[key] = res;
	} else {
		res = cache[key];
	}

	return res;
};

ResourceManager.prototype._getResourceConfigurationCulture = function ResourceManagerGetResourceConfigurationCulture() {
	var locale = this.getCultureName();
	var parentUrl = this.getSolution().getBaseURL();
	if (parentUrl[parentUrl.length - 1] != '/') {
		parentUrl += '/';
	}

	var configUrl = parentUrl + 'xml/' + this.getConfigFileName();
	var doc = this._tryGetResourceConfig(configUrl);

	return doc;
};

ResourceManager.prototype._tryGetResourceConfig = function ResourceManagerTryGetResourceConfigFromCache(url) {
	var cache = this._getCache();

	var resourceConfigFileExists = this._getFileExist(url);
	if (!resourceConfigFileExists) {
		return null;
	}

	var cachePostfix = '_config';
	var cacheKey = url + cachePostfix;

	if (cache[cacheKey]) {
		return cache[cacheKey];
	} else {
		var doc = this._getXmlDocument(url);
		cache[cacheKey] = doc;
		return doc;
	}
};

ResourceManager.prototype.getString = function ResourceManagerGetString(key) {
	/// <summary locid="M:J#Aras.Client.JS.ResourceManager.getString">
	///  Searches for localized resource by unique key and returns it's value.
	/// </summary>
	/// <param locid="M:J#Aras.Client.JS.ResourceManager.getString" name="key" type="string" mayBeNull="false">
	///	 The unique id of the resource to get.
	/// </param>
	/// <returns type="string">Gets the value of the resource localized for the specified culture.</returns>
	/// <remarks>
	///  If the resource has not been localized for that culture, the resource that is returned is localized
	///  for a best match. Otherwise, error message will be returned.
	/// </remarks>
	key = XmlUtils.escapeXPathStringCriteria(key);

	var supportedCultureList = this._getResourceConfigurationCulture();
	var path = this._getI18NResourcePath(supportedCultureList);
	var doc = this._getXmlDocument(path);
	if (!doc) {
		return 'Error loading ' + path + ' .';
	}

	var nd = doc.selectSingleNode('/*/resource[@key=' + key + ']');
	if (!nd) {
		return 'Resource with key="' + key + '" is not found in "' + path + '".';
	}

	return nd.getAttribute('value');
};

ResourceManager.prototype.getFormatedString = function ResourceManagerGetFormatedString(key, params) {
	/// <summary locid="M:J#Aras.Client.JS.ResourceManager.getFormatedString">
	///  Returns culture name. If culture parameter in cunstructor wasn't specified, then CultureInfo.CurrentCulture's name is taken.
	/// </summary>
	/// <param locid="M:J#Aras.Client.JS.ResourceManager.getFormatedString" name="key" type="string" mayBeNull="false">
	///	 The unique id of the resource to get.
	/// </param>
	/// <param locid="M:J#Aras.Client.JS.ResourceManager.getFormatedString" name="params" type="Object" mayBeNull="false">
	///	 Parameters to insert in resource's placeholders, i.e. resource "Tree error: ({0}) {1}" expects array of two parameters passed.
	/// </param>
	/// <returns type="string">Gets the value of the resource localized for the specified culture.</returns>
	/// <remarks>
	///  If the resource has not been localized for that culture, the resource that is returned is localized
	///  for a best match. Otherwise, error message will be returned.
	/// </remarks>

	var val = this.getString(key);
	if (arguments) {
		for (var i = 0; i < arguments.length; i++) {
			var re = new RegExp('\\{' + i + '\\}', 'g');
			val = val.replace(re, arguments[i + 1]);
		}
	}

	return val;
};
/*@cc_on
@if (@register_classes == 1)
Type.registerNamespace("Aras");
Type.registerNamespace("Aras.Client");
Type.registerNamespace("Aras.Client.JS");

Aras.Client.JS.ResourceManager = ResourceManager;
Aras.Client.JS.ResourceManager.registerClass("Aras.Client.JS.ResourceManager");
@end
@*/

/** innovator_update.js **/
function InnovatorUpdate() {}

InnovatorUpdate.prototype.BeginIsNeedCheckUpdates = function InnovatorUpdateBeginIsNeedCheckUpdates() {
	var arasObj = parent.aras;
	var updateInfo = arasObj.commonProperties.innovatorUpdateInfo = {key: '', iv: '', info: '', version: ''};
	var res = parent.arasMainWindowInfo.getCheckUpdateInfoResult;
	if (res.getFaultCode() === 0) {
		var updateInfoNode = res.results.selectSingleNode(arasObj.XPathResult('/UpdateNotNeeded'));
		if (updateInfoNode) {
			arasObj.commonProperties.innovatorUpdateInfo.version = updateInfoNode.text;
			return;
		}
		updateInfoNode = res.results.selectSingleNode(arasObj.XPathResult('/CheckUpdateInfo'));

		var keyNode = updateInfoNode.selectSingleNode('Key');
		var ivNode = updateInfoNode.selectSingleNode('IV');
		var infoNode = updateInfoNode.selectSingleNode('Info');
		var versionNode = updateInfoNode.selectSingleNode('Version');

		if (keyNode) {
			updateInfo.key = keyNode.text;
		}
		if (ivNode) {
			updateInfo.iv = ivNode.text;
		}
		if (infoNode) {
			updateInfo.info = infoNode.text;
		}
		if (versionNode) {
			updateInfo.version = versionNode.text;
		}
	} else {
		arasObj.AlertError('GetUpdateInfo failed');
		return;
	}

	if (updateInfo.key && updateInfo.iv && updateInfo.info) {
		getUpdateInfo();
	}

	function escapeXml(str) {
		return str.replace(/&/g, '&amp;')
				.replace(/</g, '&lt;')
				.replace(/>/g, '&gt;')
				.replace(/"/g, '&quot;');
	}

	function getUpdateInfo() {
		var method = 'SecureGetUpdateInfo';
		var methodNm = 'http://www.aras.com/Notifications';
		var str = '<info>' + escapeXml(updateInfo.info) + '</info>' +
				'<key>' + escapeXml(updateInfo.key) + '</key>' +
				'<iv>' + escapeXml(updateInfo.iv) + '</iv>';

		ArasModules.soap(str, {
			async: true,
			url: location.protocol + '//www.aras.com/notifications/updatecheck.asmx',
			method: method,
			methodNm: methodNm,
			SOAPAction: methodNm + '/' + method,
			headers: {}
		})
			.then(function(responseText) {
				var tmpContent = responseText.indexOf('<SecureGetUpdateInfoResult>');
				if (tmpContent > -1) {
					tmpContent = responseText.substr(
						tmpContent,
						responseText.indexOf('</SecureGetUpdateInfoResult>') + '</SecureGetUpdateInfoResult>'.length - tmpContent
					);

					var dom = arasObj.createXMLDocument();

					dom.loadXML(tmpContent);
					tmpContent = dom.selectSingleNode('/*/content');

					var tmpSignature = dom.selectSingleNode('/*/signature');

					storeToVersionFile(tmpContent ? tmpContent.text : null, tmpSignature ? tmpSignature.text : null);
				}
			});
	}

	function storeToVersionFile(updateInfoContent, updateInfoSignature) {
		if (!updateInfoContent) {
			return;
		}

		var xml = '<UpdateInfo>' +
				'<content xmlns="http://www.aras.com/Notifications">' + escapeXml(updateInfoContent) + '</content>' +
				'<signature xmlns="http://www.aras.com/Notifications">' + escapeXml(updateInfoSignature) + '</signature>' +
				'</UpdateInfo>';

		arasObj.soapSend('StoreVersionFile', xml, undefined, undefined, new SoapController(function() {}));
	}
};

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

/** ../vendors/jstz.min.js **/
!function(a){var b=function(){"use strict";var a="s",c={DAY:864e5,HOUR:36e5,MINUTE:6e4,SECOND:1e3,BASELINE_YEAR:2016,MAX_SCORE:864e6,AMBIGUITIES:{"America/Denver":["America/Mazatlan"],"Europe/London":["Africa/Casablanca"],"America/Chicago":["America/Mexico_City"],"America/Asuncion":["America/Campo_Grande","America/Santiago"],"America/Montevideo":["America/Sao_Paulo","America/Santiago"],"Asia/Beirut":["Asia/Amman","Asia/Jerusalem","Europe/Helsinki","Asia/Damascus","Africa/Cairo","Asia/Gaza","Europe/Minsk"],"Pacific/Auckland":["Pacific/Fiji"],"America/Los_Angeles":["America/Santa_Isabel"],"America/New_York":["America/Havana"],"America/Halifax":["America/Goose_Bay"],"America/Godthab":["America/Miquelon"],"Asia/Dubai":["Asia/Yerevan"],"Asia/Jakarta":["Asia/Krasnoyarsk"],"Asia/Shanghai":["Asia/Irkutsk","Australia/Perth"],"Australia/Sydney":["Australia/Lord_Howe"],"Asia/Tokyo":["Asia/Yakutsk"],"Asia/Dhaka":["Asia/Omsk"],"Asia/Baku":["Asia/Yerevan"],"Australia/Brisbane":["Asia/Vladivostok"],"Pacific/Noumea":["Asia/Vladivostok"],"Pacific/Majuro":["Asia/Kamchatka","Pacific/Fiji"],"Pacific/Tongatapu":["Pacific/Apia"],"Asia/Baghdad":["Europe/Minsk","Europe/Moscow"],"Asia/Karachi":["Asia/Yekaterinburg"],"Africa/Johannesburg":["Asia/Gaza","Africa/Cairo"]}},d=function(b){var c=-b.getTimezoneOffset();return null!==c?c:0},e=function(){var e=d(new Date(c.BASELINE_YEAR,0,2)),f=d(new Date(c.BASELINE_YEAR,5,2)),g=e-f;return g<0?e+",1":g>0?f+",1,"+a:e+",0"},f=function(){var b,c;if("undefined"!=typeof Intl&&"undefined"!=typeof Intl.DateTimeFormat){try{b=Intl.DateTimeFormat()}catch(a){return}if("undefined"!=typeof b&&"undefined"!=typeof b.resolvedOptions)return c=b.resolvedOptions().timeZone,c&&(c.indexOf("/")>-1||"UTC"===c)?c:void 0}},g=function(b){for(var c=new Date(b,0,1,0,0,1,0).getTime(),d=new Date(b,12,31,23,59,59).getTime(),e=c,f=new Date(e).getTimezoneOffset(),g=null,i=null;e<d-864e5;){var j=new Date(e),k=j.getTimezoneOffset();k!==f&&(k<f&&(g=j),k>f&&(i=j),f=k),e+=864e5}return!(!g||!i)&&{s:h(g).getTime(),e:h(i).getTime()}},h=function a(b,d,e){"undefined"==typeof d&&(d=c.DAY,e=c.HOUR);for(var f=new Date(b.getTime()-d).getTime(),g=b.getTime()+d,h=new Date(f).getTimezoneOffset(),i=f,j=null;i<g-e;){var k=new Date(i),l=k.getTimezoneOffset();if(l!==h){j=k;break}i+=e}return d===c.DAY?a(j,c.HOUR,c.MINUTE):d===c.HOUR?a(j,c.MINUTE,c.SECOND):j},i=function(a,c){var d=a,e=new Date,f=e.toLocaleString("en-US",{timeZoneName:"long"}),h=e.toLocaleString("en-US"),i=f.slice(h.length).trim(),j=[i];j.push(i.replace("Daylight","Standard").replace("Summer","Standard")),j.push(i.replace("Standard","Daylight")),j.push(i.replace("Standard","Summer"));var k=navigator.userAgent.indexOf("Firefox")!==-1,l=k?b.olson.new_rules.firefox[c]:b.olson.new_rules.ie[c],m=k?b.olson.new_rules_win7.firefox[c]:b.olson.new_rules_win7.ie[c];return m&&(l=l.concat(m)),l&&l.forEach(function(a){var b=g(a.year);b.s===a.dst.s&&b.e===a.dst.e&&(!k||j.indexOf(a.tzEnUs)>-1)&&(d=a.tz)}),d},j=function(){var c=f();if(!c){c=b.olson.timezones[e()];var g=d(new Date(2016,0,2)),h=d(new Date(2016,5,2));c=i(c,g),c=i(c,h)}return{name:function(){return c}}};return{determine:j}}();b.olson=b.olson||{},b.olson.timezones={"-720,0":"Etc/GMT+12","-660,0":"Pacific/Pago_Pago","-660,1,s":"Pacific/Apia","-600,1":"America/Adak","-600,0":"Pacific/Honolulu","-570,0":"Pacific/Marquesas","-540,0":"Pacific/Gambier","-540,1":"America/Anchorage","-480,1":"America/Los_Angeles","-480,0":"Pacific/Pitcairn","-420,0":"America/Phoenix","-420,1":"America/Denver","-360,0":"America/Guatemala","-360,1":"America/Chicago","-360,1,s":"Pacific/Easter","-300,0":"America/Bogota","-300,1":"America/New_York","-270,0":"America/Caracas","-240,1":"America/Halifax","-240,0":"America/Santo_Domingo","-240,1,s":"America/Asuncion","-210,1":"America/St_Johns","-180,1":"America/Godthab","-180,0":"America/Buenos_Aires","-180,1,s":"America/Montevideo","-120,0":"America/Noronha","-120,1":"America/Noronha","-60,1":"Atlantic/Azores","-60,0":"Atlantic/Cape_Verde","0,0":"UTC","0,1":"Europe/London","60,1":"Europe/Berlin","60,0":"Africa/Lagos","60,1,s":"Africa/Windhoek","120,1":"Asia/Beirut","120,0":"Africa/Johannesburg","180,0":"Asia/Baghdad","180,1":"Europe/Moscow","210,1":"Asia/Tehran","240,0":"Asia/Dubai","240,1":"Asia/Baku","270,0":"Asia/Kabul","300,1":"Asia/Yekaterinburg","300,0":"Asia/Karachi","330,0":"Asia/Calcutta","345,0":"Asia/Katmandu","360,0":"Asia/Dhaka","360,1":"Asia/Omsk","360,1,s":"Asia/Novosibirsk","390,0":"Asia/Rangoon","420,1":"Asia/Krasnoyarsk","420,0":"Asia/Jakarta","480,0":"Asia/Shanghai","480,1":"Asia/Irkutsk","525,0":"Australia/Eucla","525,1,s":"Australia/Eucla","540,1":"Asia/Yakutsk","540,0":"Asia/Tokyo","570,0":"Australia/Darwin","570,1,s":"Australia/Adelaide","600,0":"Australia/Brisbane","600,1":"Asia/Vladivostok","600,1,s":"Australia/Sydney","630,1,s":"Australia/Lord_Howe","660,1":"Asia/Kamchatka","660,0":"Pacific/Noumea","690,0":"Pacific/Norfolk","720,1,s":"Pacific/Auckland","720,0":"Pacific/Majuro","765,1,s":"Pacific/Chatham","780,0":"Pacific/Tongatapu","780,1,s":"Pacific/Apia","840,0":"Pacific/Kiritimati"},b.olson.new_rules={ie:{0:[{tz:"Africa/Casablanca",year:"2016",dst:{s:1459044e6,e:14777928e5}},{tz:"Europe/London",year:"2016",dst:{s:14590404e5,e:14777892e5}}],60:[{tz:"Africa/Lagos",year:"2016",dst:!1},{tz:"Africa/Windhoek",year:"2016",dst:{s:14729508e5,e:14596416e5}}],120:[{tz:"Asia/Amman",year:"2016",dst:{s:14594616e5,e:14776056e5}},{tz:"Asia/Beirut",year:"2016",dst:{s:14590296e5,e:14777748e5}},{tz:"Africa/Cairo",year:"2014",dst:{s:14001912e5,e:14116788e5}},{tz:"Europe/Chisinau",year:"2016",dst:{s:14590368e5,e:14777856e5}},{tz:"Europe/Kaliningrad",year:"2010",dst:{s:12697344e5,e:12884832e5}},{tz:"Asia/Damascus",year:"2016",dst:{s:14588568e5,e:1477602e6}},{tz:"Asia/Hebron",year:"2016",dst:{s:14589468e5,e:14769972e5}},{tz:"Asia/Jerusalem",year:"2016",dst:{s:1458864e6,e:1477782e6}}],180:[{tz:"Asia/Baghdad",year:"2007",dst:{s:11753856e5,e:11911968e5}},{tz:"Europe/Istanbul",year:"2015",dst:{s:14275908e5,e:14469444e5}},{tz:"Europe/Minsk",year:"2010",dst:{s:12697344e5,e:12884832e5}},{tz:"Europe/Moscow",year:"2010",dst:{s:12697308e5,e:12884796e5}}],210:[{tz:"Asia/Tehran",year:"2016",dst:{s:14585058e5,e:14743998e5}}],240:[{tz:"Europe/Astrakhan",year:"2009",dst:{s:12382812e5,e:12564252e5}},{tz:"Asia/Baku",year:"2015",dst:{s:14275872e5,e:14457312e5}},{tz:"Europe/Samara",year:"2009",dst:{s:12382776e5,e:12622896e5}},{tz:"Asia/Yerevan",year:"2011",dst:{s:13011768e5,e:13199256e5}}],270:[{tz:"Asia/Kabul",year:"2016",dst:!1}],300:[{tz:"Asia/Tashkent",year:"2009",dst:!1},{tz:"Asia/Yekaterinburg",year:"2009",dst:{s:1238274e6,e:1256418e6}},{tz:"Asia/Karachi",year:"2009",dst:{s:12397356e5,e:1257012e6}}],330:[],345:[{tz:"Asia/Katmandu",year:"2016",dst:!1}],360:[{tz:"Asia/Almaty",year:"2009",dst:!1},{tz:"Asia/Dhaka",year:"2009",dst:{s:12454308e5,e:12622788e5}},{tz:"Asia/Omsk",year:"2009",dst:{s:12382704e5,e:12564144e5}}],390:[{tz:"Asia/Rangoon",year:"2016",dst:!1}],420:[{tz:"Asia/Bangkok",year:"2010",dst:!1},{tz:"Asia/Hovd",year:"2016",dst:{s:14589324e5,e:14746464e5}},{tz:"Asia/Krasnoyarsk",year:"2010",dst:{s:12697164e5,e:12884652e5}}],480:[{tz:"Asia/Ulaanbaatar",year:"2016",dst:{s:14589288e5,e:14746428e5}},{tz:"Australia/Perth",year:"2008",dst:{s:12249576e5,e:12068136e5}},{tz:"Asia/Irkutsk",year:"2010",dst:{s:12697128e5,e:12884616e5}}],510:[{tz:"Asia/Pyongyang",year:"2016",dst:!1}],525:[{tz:"Australia/Eucla",year:"2016",dst:!1}],540:[],570:[{tz:"Australia/Adelaide",year:"2016",dst:{s:14753394e5,e:14596146e5}},{tz:"Australia/Darwin",year:"2016",dst:!1}],600:[{tz:"Australia/Sydney",year:"2007",dst:{s:11935008e5,e:1174752e6}},{tz:"Australia/Hobart",year:"2007",dst:{s:11916864e5,e:1174752e6}},{tz:"Asia/Vladivostok",year:"2010",dst:{s:12697056e5,e:12884544e5}}],630:[{tz:"Australia/Lord_Howe",year:"2016",dst:{s:14753358e5,e:14596092e5}}],660:[{tz:"Asia/Sakhalin",year:"2010",dst:{s:12697056e5,e:12884544e5}}],720:[{tz:"Asia/Kamchatka",year:"2010",dst:{s:1269702e6,e:12884508e5}},{tz:"Pacific/Auckland",year:"2010",dst:{s:12854232e5,e:12703032e5}},{tz:"Etc/GMT-12",year:"2010",dst:!1},{tz:"Pacific/Fiji",year:"2010",dst:{s:12878424e5,e:12696984e5}}],765:[{tz:"Pacific/Chatham",year:"2016",dst:{s:14747256e5,e:14596056e5}}],780:[{tz:"Pacific/Tongatapu",year:"2016",dst:!1},{tz:"Pacific/Apia",year:"2016",dst:{s:14747256e5,e:14596056e5}}],840:[{tz:"Pacific/Kiritimati",year:"2016",dst:!1}],"-720":[{tz:"Etc/GMT+12",year:"2016",dst:!1}],"-660":[{tz:"Etc/GMT+11",year:"2016",dst:!1}],"-600":[{tz:"America/Adak",year:"2016",dst:{s:14578704e5,e:147843e7}},{tz:"Pacific/Honolulu",year:"2016",dst:!1}],"-570":[{tz:"Pacific/Marquesas",year:"2016",dst:!1}],"-540":[{tz:"America/Anchorage",year:"2016",dst:{s:14578668e5,e:14784264e5}},{tz:"Etc/GMT+9",year:"2016",dst:!1}],"-480":[{tz:"America/Tijuana",year:"2009",dst:{s:12389256e5,e:12564612e5}},{tz:"Etc/GMT+8",year:"2009",dst:!1},{tz:"America/Los_Angeles",year:"2009",dst:{s:12365064e5,e:1257066e6}}],"-420":[{tz:"America/Phoenix",year:"2016",dst:!1},{tz:"America/Chihuahua",year:"2016",dst:{s:1459674e6,e:14778144e5}},{tz:"America/Denver",year:"2016",dst:{s:14578596e5,e:14784192e5}}],"-210":[{tz:"America/St_Johns",year:"2016",dst:{s:1457847e6,e:14784066e5}}],"-120":[{tz:"Etc/GMT+2",year:"2016",dst:!1}],"-60":[{tz:"Atlantic/Azores",year:"2016",dst:{s:14590404e5,e:14777892e5}},{tz:"Atlantic/Cape_Verde",year:"2016",dst:!1}],"-360":[{tz:"America/Chicago",year:"2016",dst:{s:1457856e6,e:14784156e5}},{tz:"America/Mexico_City",year:"2016",dst:{s:14596704e5,e:14778108e5}},{tz:"Pacific/Easter",year:"2016",dst:{s:14711472e5,e:14632812e5}}],"-300":[{tz:"America/Bogota",year:"2014",dst:!1},{tz:"America/Indianapolis",year:"2005",dst:!1},{tz:"America/Cancun",year:"2014",dst:{s:13967712e5,e:14143068e5}},{tz:"America/New_York",year:"2005",dst:{s:11125116e5,e:1130652e6}},{tz:"America/Port-au-Prince",year:"2015",dst:{s:1425798e6,e:14463576e5}},{tz:"America/Havana",year:"2016",dst:{s:14578452e5,e:14784084e5}}],"-240":[{tz:"America/Asuncion",year:"2016",dst:{s:14753808e5,e:14590476e5}},{tz:"America/Halifax",year:"2016",dst:{s:14578488e5,e:14784084e5}},{tz:"America/Cuiaba",year:"2016",dst:{s:14765904e5,e:14560236e5}},{tz:"America/Santiago",year:"2016",dst:{s:14711472e5,e:14632812e5}},{tz:"America/Grand_Turk",year:"2014",dst:{s:13943484e5,e:1414908e6}}],"-180":[{tz:"America/Buenos_Aires",year:"2008",dst:{s:12243852e5,e:12056328e5}},{tz:"America/Sao_Paulo",year:"2016",dst:{s:14765868e5,e:145602e7}},{tz:"America/Godthab",year:"2016",dst:{s:14590404e5,e:14777892e5}},{tz:"America/Montevideo",year:"2014",dst:{s:14124852e5,e:13943376e5}},{tz:"America/Miquelon",year:"2016",dst:{s:14578452e5,e:14784048e5}}]},firefox:{0:[{tz:"Etc/GMT",year:"2016",dst:!1,tzEnUs:"GMT"},{tz:"Africa/Casablanca",year:"2016",dst:{s:1459044e6,e:14777928e5},tzEnUs:"Western European Summer Time"},{tz:"Europe/London",year:"2016",dst:{s:14590404e5,e:14777892e5},tzEnUs:"British Summer Time"},{tz:"Atlantic/Reykjavik",year:"2016",dst:!1,tzEnUs:"Greenwich Mean Time"}],60:[{tz:"Africa/Lagos",year:"2016",dst:!1,tzEnUs:"West Africa Standard Time"},{tz:"Africa/Windhoek",year:"2016",dst:{s:14729508e5,e:14596416e5},tzEnUs:"West Africa Summer Time"}],120:[{tz:"Asia/Amman",year:"2016",dst:{s:14594616e5,e:14776056e5},tzEnUs:"Eastern European Summer Time"},{tz:"Asia/Beirut",year:"2016",dst:{s:14590296e5,e:14777748e5},tzEnUs:"Eastern European Summer Time"},{tz:"Europe/Chisinau",year:"2016",dst:{s:14590368e5,e:14777856e5},tzEnUs:"GMT+02:00"},{tz:"Asia/Damascus",year:"2016",dst:{s:14588568e5,e:1477602e6},tzEnUs:"Eastern European Summer Time"},{tz:"Asia/Hebron",year:"2016",dst:{s:14589468e5,e:14769972e5},tzEnUs:"GMT+02:00"},{tz:"Africa/Johannesburg",year:"2016",dst:!1,tzEnUs:"South Africa Standard Time"},{tz:"Asia/Jerusalem",year:"2016",dst:{s:1458864e6,e:1477782e6},tzEnUs:"Israel Daylight Time"}],180:[{tz:"Europe/Istanbul",year:"2016",dst:{s:14590404e5,e:148365e7},tzEnUs:"Eastern European Summer Time"},{tz:"Europe/Minsk",year:"2016",dst:!1,tzEnUs:"Further-eastern European Time"},{tz:"Europe/Moscow",year:"2016",dst:!1,tzEnUs:"Moscow Standard Time"},{tz:"Africa/Nairobi",year:"2016",dst:!1,tzEnUs:"East Africa Time"}],210:[{tz:"Asia/Tehran",year:"2016",dst:{s:14585058e5,e:14743998e5},tzEnUs:"Iran Standard Time"}],240:[{tz:"Asia/Dubai",year:"2016",dst:!1,tzEnUs:"Gulf Standard Time"},{tz:"Europe/Astrakhan",year:"2016",dst:{s:14590332e5,e:14836464e5},tzEnUs:"GMT+04:00"},{tz:"Asia/Baku",year:"2016",dst:!1,tzEnUs:"Azerbaijan Summer Time"},{tz:"Europe/Samara",year:"2016",dst:!1,tzEnUs:"Samara Standard Time"},{tz:"Indian/Mauritius",year:"2016",dst:!1,tzEnUs:"Mauritius Standard Time"},{tz:"Asia/Tbilisi",year:"2016",dst:!1,tzEnUs:"Georgia Standard Time"},{tz:"Asia/Yerevan",year:"2016",dst:!1,tzEnUs:"Armenia Standard Time"}],270:[{tz:"Asia/Kabul",year:"2016",dst:!1,tzEnUs:"Afghanistan Time"}],300:[{tz:"Asia/Tashkent",year:"2016",dst:!1,tzEnUs:"Uzbekistan Standard Time"},{tz:"Asia/Yekaterinburg",year:"2016",dst:!1,tzEnUs:"Yekaterinburg Standard Time"},{tz:"Asia/Karachi",year:"2016",dst:!1,tzEnUs:"Pakistan Standard Time"}],330:[],345:[{tz:"Asia/Katmandu",year:"2016",dst:!1,tzEnUs:"Nepal Time"}],360:[{tz:"Asia/Almaty",year:"2016",dst:!1,tzEnUs:"East Kazakhstan Time"},{tz:"Asia/Dhaka",year:"2016",dst:!1,tzEnUs:"Bangladesh Standard Time"},{tz:"Asia/Omsk",year:"2016",dst:!1,tzEnUs:"GMT+06:00"},{tz:"Asia/Novosibirsk",year:"2016",dst:{s:1469304e6,e:14836356e5},tzEnUs:"Novosibirsk Standard Time"}],390:[{tz:"Asia/Rangoon",year:"2016",dst:!1,tzEnUs:"Myanmar Time"}],420:[{tz:"Asia/Bangkok",year:"2016",dst:!1,tzEnUs:"Indochina Time"},{tz:"Asia/Barnaul",year:"2016",dst:{s:14590224e5,e:14836356e5},tzEnUs:"GMT+07:00"},{tz:"Asia/Hovd",year:"2016",dst:{s:14589324e5,e:14746464e5},tzEnUs:"GMT+07:00"},{tz:"Asia/Krasnoyarsk",year:"2016",dst:!1,tzEnUs:"Krasnoyarsk Standard Time"},{tz:"Asia/Novosibirsk",year:"2016",dst:{s:1469304e6,e:14836356e5},tzEnUs:"Novosibirsk Standard Time"},{tz:"Asia/Tomsk",year:"2016",dst:{s:14644656e5,e:14836356e5},tzEnUs:"GMT+07:00"}],480:[{tz:"Asia/Shanghai",year:"2016",dst:!1,tzEnUs:"China Standard Time"},{tz:"Asia/Irkutsk",year:"2016",dst:!1,tzEnUs:"Irkutsk Standard Time"},{tz:"Asia/Singapore",year:"2016",dst:!1,tzEnUs:"Singapore Standard Time"},{tz:"Australia/Perth",year:"2016",dst:!1,tzEnUs:"Australian Western Standard Time"},{tz:"Asia/Taipei",year:"2016",dst:!1,tzEnUs:"Taipei Standard Time"},{tz:"Asia/Ulaanbaatar",year:"2016",dst:{s:14589288e5,e:14746428e5},tzEnUs:"Ulan Bator Standard Time"}],510:[{tz:"Asia/Pyongyang",year:"2016",dst:!1,tzEnUs:"GMT+08:30"}],525:[{tz:"Australia/Eucla",year:"2016",dst:!1,tzEnUs:"GMT+08:45"}],540:[{tz:"Asia/Chita",year:"2016",dst:{s:14590152e5,e:14836284e5},tzEnUs:"GMT+09:00"},{tz:"Asia/Tokyo",year:"2016",dst:!1,tzEnUs:"Japan Standard Time"},{tz:"Asia/Seoul",year:"2016",dst:!1,tzEnUs:"Korean Standard Time"},{tz:"Asia/Yakutsk",year:"2016",dst:!1,tzEnUs:"Yakutsk Standard Time"}],570:[{tz:"Australia/Adelaide",year:"2016",dst:{s:14753394e5,e:14596146e5},tzEnUs:"Australian Central Daylight Time"},{tz:"Australia/Darwin",year:"2016",dst:!1,tzEnUs:"Australian Central Standard Time"}],600:[{tz:"Australia/Brisbane",year:"2016",dst:!1,tzEnUs:"Australian Eastern Standard Time"},{tz:"Pacific/Port_Moresby",year:"2016",dst:!1,tzEnUs:"Papua New Guinea Time"},{tz:"Asia/Vladivostok",year:"2016",dst:!1,tzEnUs:"Vladivostok Standard Time"}],630:[{tz:"Australia/Lord_Howe",year:"2016",dst:{s:14753358e5,e:14596092e5},tzEnUs:"GMT+10:30"}],660:[{tz:"Asia/Magadan",year:"2016",dst:{s:14614272e5,e:14836212e5},tzEnUs:"Magadan Standard Time"},{tz:"Asia/Sakhalin",year:"2016",dst:{s:1459008e6,e:14836212e5},tzEnUs:"GMT+11:00"},{tz:"Pacific/Guadalcanal",year:"2016",dst:!1,tzEnUs:"Solomon Islands Time"}],720:[{tz:"Asia/Kamchatka",year:"2016",dst:!1,tzEnUs:"Petropavlovsk-Kamchatski Standard Time"},{tz:"Pacific/Auckland",year:"2016",dst:{s:14747256e5,e:14596056e5},tzEnUs:"New Zealand Daylight Time"},{tz:"Etc/GMT-12",year:"2016",dst:!1,tzEnUs:"GMT+12:00"},{tz:"Pacific/Fiji",year:"2016",dst:{s:14783544e5,e:14844024e5},tzEnUs:"Fiji Standard Time"}],765:[{tz:"Pacific/Chatham",year:"2016",dst:{s:14747256e5,e:14596056e5},tzEnUs:"GMT+12:45"}],780:[{tz:"Pacific/Tongatapu",year:"2016",dst:!1,tzEnUs:"Tonga Standard Time"},{tz:"Pacific/Apia",year:"2016",dst:{s:14747256e5,e:14596056e5},tzEnUs:"Apia Daylight Time"}],840:[{tz:"Pacific/Kiritimati",year:"2016",dst:!1,tzEnUs:"Line Islands Time"}],"-720":[{tz:"Etc/GMT+12",year:"2016",dst:!1,tzEnUs:"GMT-12:00"}],"-660":[{tz:"Etc/GMT+11",year:"2016",dst:!1,tzEnUs:"GMT-11:00"}],"-600":[{tz:"America/Adak",year:"2016",dst:{s:14578704e5,e:147843e7},tzEnUs:"GMT-10:00"},{tz:"Pacific/Honolulu",year:"2016",dst:!1,tzEnUs:"Hawaii-Aleutian Standard Time"}],"-570":[{tz:"Pacific/Marquesas",year:"2016",dst:!1,tzEnUs:"GMT-09:30"}],"-540":[{tz:"America/Anchorage",year:"2016",dst:{s:14578668e5,e:14784264e5},tzEnUs:"Alaska Daylight Time"},{tz:"Etc/GMT+9",year:"2016",dst:!1,tzEnUs:"GMT-09:00"}],"-480":[{tz:"America/Tijuana",year:"2016",dst:{s:14578632e5,e:14784228e5},tzEnUs:"Northwest Mexico Daylight Time"},{tz:"Etc/GMT+8",year:"2016",dst:!1,tzEnUs:"GMT-08:00"},{tz:"America/Los_Angeles",year:"2016",dst:{s:14578632e5,e:14784228e5},tzEnUs:"Pacific Daylight Time"}],"-420":[{tz:"America/Phoenix",year:"2016",dst:!1,tzEnUs:"Mountain Standard Time"},{tz:"America/Chihuahua",year:"2016",dst:{s:1459674e6,e:14778144e5},tzEnUs:"Mexican Pacific Daylight Time"},{tz:"America/Denver",year:"2016",dst:{s:14578596e5,e:14784192e5},tzEnUs:"Mountain Daylight Time"}],"-240":[{tz:"America/Asuncion",year:"2016",dst:{s:14753808e5,e:14590476e5},tzEnUs:"Paraguay Summer Time"},{tz:"America/Halifax",year:"2016",dst:{s:14578488e5,e:14784084e5},tzEnUs:"Atlantic Daylight Time"},{tz:"America/Caracas",year:"2016",dst:{s:1462086e6,e:14836752e5},tzEnUs:"Venezuela Time"},{tz:"America/Cuiaba",year:"2016",dst:{s:14765904e5,e:14560236e5},tzEnUs:"Amazon Summer Time"},{tz:"America/La_Paz",year:"2016",dst:!1,tzEnUs:"Bolivia Time"},{tz:"America/Santiago",year:"2016",dst:{s:14711472e5,e:14632812e5},tzEnUs:"Chile Standard Time"},{tz:"America/Grand_Turk",year:"2016",dst:!1,tzEnUs:"GMT-04:00"}],"-210":[{tz:"America/St_Johns",year:"2016",dst:{s:1457847e6,e:14784066e5},tzEnUs:"Newfoundland Daylight Time"}],"-180":[{tz:"America/Araguaina",year:"2016",dst:!1,tzEnUs:"GMT-03:00"},{tz:"America/Sao_Paulo",year:"2016",dst:{s:14765868e5,e:145602e7},tzEnUs:"Brasilia Summer Time"},{tz:"America/Cayenne",year:"2016",dst:!1,tzEnUs:"French Guiana Time"},{tz:"America/Buenos_Aires",year:"2016",dst:!1,tzEnUs:"Argentina Standard Time"},{tz:"America/Godthab",year:"2016",dst:{s:14590404e5,e:14777892e5},tzEnUs:"West Greenland Summer Time"},{tz:"America/Montevideo",year:"2016",dst:!1,tzEnUs:"Uruguay Standard Time"},{tz:"America/Miquelon",year:"2016",dst:{s:14578452e5,e:14784048e5},tzEnUs:"GMT-03:00"},{tz:"America/Bahia",year:"2016",dst:!1,tzEnUs:"Brasilia Standard Time"}],"-120":[{tz:"Etc/GMT+2",year:"2016",dst:!1,tzEnUs:"GMT-02:00"}],"-60":[{tz:"Atlantic/Azores",year:"2016",dst:{s:14777892e5,e:14590404e5},tzEnUs:"Azores Summer Time"},{tz:"Atlantic/Cape_Verde",year:"2016",dst:!1,tzEnUs:"Cape Verde Standard Time"}],"-360":[{tz:"America/Chicago",year:"2016",dst:{s:1457856e6,e:14784156e5},tzEnUs:"Central Daylight Time"},{tz:"Pacific/Easter",year:"2016",dst:{s:14711472e5,e:14632812e5},tzEnUs:"GMT-06:00"},{tz:"America/Mexico_City",year:"2016",dst:{s:14596704e5,e:14778108e5},tzEnUs:"Central Daylight Time"}],"-300":[{tz:"America/Bogota",year:"2016",dst:!1,tzEnUs:"Colombia Standard Time"},{tz:"America/Cancun",year:"2016",dst:!1,tzEnUs:"Eastern Standard Time"},{tz:"America/Port-au-Prince",year:"2016",dst:!1,tzEnUs:"GMT-05:00"},{tz:"America/Havana",year:"2016",dst:{s:14578452e5,e:14784084e5},tzEnUs:"GMT-05:00"}]}},b.olson.new_rules_win7={ie:{0:[{tz:"Africa/Casablanca",year:"2016",dst:{s:1468116e6,e:14777928e5}}],120:[{tz:"Europe/Istanbul",year:"2015",dst:{s:14275908e5,e:14469444e5}}],240:[{tz:"Europe/Astrakhan",year:"2010",dst:{s:12697308e5,e:12884796e5}},{tz:"Europe/Samara",year:"2009",dst:{s:12382776e5,e:12564216e5}}],360:[{tz:"Asia/Omsk",year:"2009",dst:{s:12382704e5,e:12564144e5}}],720:[{tz:"Asia/Kamchatka",year:"2009",dst:{s:12382488e5,e:12563928e5}},{tz:"Pacific/Auckland",year:"2016",dst:{s:14747256e5,e:14596056e5}},{tz:"Pacific/Fiji",year:"2016",dst:{s:14783544e5,e:14844024e5}},{tz:"Etc/GMT-12",year:"2009",dst:!1}],"-240":[{tz:"America/Asuncion",year:"2007",dst:{s:11929392e5,e:1173582e6}},{tz:"America/Caracas",year:"2007",dst:{s:11676258e5,e:11971836e5}},{tz:"America/Cuiaba",year:"2007",dst:{s:11923344e5,e:11723724e5}},{tz:"America/Santiago",year:"2007",dst:{s:11923344e5,e:1173582e6}},{tz:"America/La_Paz",year:"2007",dst:!1},{tz:"America/Grand_Turk",year:"2007",dst:{s:11735964e5,e:1194156e6}},{tz:"America/Halifax",year:"2007",dst:{s:11735928e5,e:11941524e5}}],"-180":[{tz:"America/Araguaina",year:"2013",dst:{s:13570092e5,e:13610664e5}},{tz:"America/Cayenne",year:"2009",dst:!1},{tz:"America/Bahia",year:"2012",dst:{s:13253868e5,e:13302216e5}},{tz:"America/Buenos_Aires",year:"2009",dst:{s:12307788e5,e:12370824e5}},{tz:"America/Montevideo",year:"2015",dst:{s:14200812e5,e:14257872e5}}]},firefox:{0:[{tz:"Africa/Casablanca",year:"2016",dst:{s:1468116e6,e:14777928e5},tzEnUs:"Western European Standard Time"},{tz:"Europe/London",year:"2016",dst:{s:14590404e5,e:14777892e5},tzEnUs:"Greenwich Mean Time"}],120:[{tz:"Asia/Amman",year:"2016",dst:{s:14594616e5,e:14776056e5},tzEnUs:"Eastern European Standard Time"},{tz:"Asia/Jerusalem",year:"2016",dst:{s:1458864e6,e:1477782e6},tzEnUs:"Israel Standard Time"},{tz:"Asia/Damascus",year:"2016",dst:{s:14588568e5,e:1477602e6},tzEnUs:"Eastern European Standard Time"},{tz:"Asia/Beirut",year:"2016",dst:{s:14590296e5,e:14777748e5},tzEnUs:"Eastern European Standard Time"}],240:[{tz:"Asia/Baku",year:"2016",dst:!1,tzEnUs:"Azerbaijan Standard Time"}],660:[{tz:"Asia/Srednekolymsk",year:"2016",dst:!1,tzEnUs:"GMT+11:00"}],720:[{tz:"Pacific/Fiji",year:"2016",dst:{s:14783544e5,e:14844024e5},tzEnUs:"Fiji Summer Time"}],"-540":[{tz:"America/Anchorage",year:"2016",dst:{s:14578668e5,e:14784264e5},tzEnUs:"Alaska Standard Time"}],"-480":[{tz:"America/Tijuana",year:"2016",dst:{s:14578632e5,e:14784228e5},tzEnUs:"Northwest Mexico Standard Time"},{tz:"America/Los_Angeles",year:"2016",dst:{s:14578632e5,e:14784228e5},tzEnUs:"Pacific Standard Time"}],"-420":[{tz:"America/Chihuahua",year:"2016",dst:{s:1459674e6,e:14778144e5},tzEnUs:"Mexican Pacific Standard Time"},{tz:"America/Denver",year:"2016",dst:{s:14578596e5,e:14784192e5},tzEnUs:"Mountain Standard Time"}],"-210":[{tz:"America/St_Johns",year:"2016",dst:{s:1457847e6,e:14784066e5},tzEnUs:"Newfoundland Standard Time"}],"-60":[{tz:"Atlantic/Azores",year:"2016",dst:{s:14590404e5,e:14777892e5},tzEnUs:"Azores Standard Time"}],"-360":[{tz:"America/Mexico_City",year:"2016",dst:{s:14596704e5,e:14778108e5},tzEnUs:"Central Standard Time"},{tz:"America/Chicago",year:"2016",dst:{s:1457856e6,e:14784156e5},tzEnUs:"Central Standard Time"}],"-240":[{tz:"America/Halifax",year:"2016",dst:{s:14578488e5,e:14784084e5},tzEnUs:"Atlantic Standard Time"}],"-180":[{tz:"America/Godthab",year:"2016",dst:{s:14590404e5,e:14777892e5},tzEnUs:"West Greenland Standard Time"}]}},"undefined"!=typeof module&&"undefined"!=typeof module.exports?module.exports=b:"undefined"==typeof a?window.jstz=b:a.jstz=b}();
/** makeItCaseInsensetive.js **/
/*
makeItCaseInsensetive.js
makeItCaseInsensetive(types) duplicates all functions in current type with the same ones with another names.
The first character in new methods names are replaced with character with inverted case.
*/

(function() {
	function invertFirstLetterCase(name) {
		var firstCharacter = name.charAt(0);
		var isUpperCase = (firstCharacter === firstCharacter.toUpperCase());
		firstCharacter = isUpperCase ? firstCharacter.toLowerCase() : firstCharacter.toUpperCase();
		return firstCharacter + name.slice(1);
	}

	window.makeItCaseInsensetive = function() {

		for (var i = 0; i < arguments.length; i++) {
			var type = arguments[i];
			var memberName;
			var j;

			var methods = [];
			// protype methods
			for (memberName in type.prototype) {
				if (typeof (type.prototype[memberName]) === 'function') {
					methods.push(memberName);
				}
			}

			for (j = 0; j < methods.length; j++) {
				memberName = methods[j];
				type.prototype[invertFirstLetterCase(memberName)] = type.prototype[memberName];
			}

			methods = [];
			// type methods
			for (memberName in type) {
				if (typeof (type[memberName]) === 'function') {
					methods.push(memberName);
				}
			}

			for (j = 0; j < methods.length; j++) {
				memberName = methods[j];
				type[invertFirstLetterCase(memberName)] = type[memberName];
			}
		}
	};
})();

/** mscorlib.js **/
(function(){var e={version:"0.7.4.0",isUndefined:function(a){return a===undefined},isNull:function(a){return a===null},isNullOrUndefined:function(a){return a===null||a===undefined},isValue:function(a){return a!==null&&a!==undefined}},g=false,a=[];function d(b){a?a.push(b):setTimeout(b,0)}function b(){if(a){var c=a;a=null;for(var b=0,d=c.length;b<d;b++)c[b]()}}if(document.addEventListener)document.readyState=="complete"?b():document.addEventListener("DOMContentLoaded",b,false);else window.attachEvent&&window.attachEvent("onload",function(){b()});var c=window.ss;if(!c)window.ss=c={init:d,ready:d};for(var f in e)c[f]=e[f]})();Object.__typeName="Object";Object.__baseType=null;Object.clearKeys=function(a){for(var b in a)delete a[b]};Object.keyExists=function(b,a){return b[a]!==undefined};if(!Object.keys){Object.keys=function(b){var a=[];for(var c in b)a.push(c);return a};Object.getKeyCount=function(b){var a=0;for(var c in b)a++;return a}}else Object.getKeyCount=function(a){return Object.keys(a).length};Boolean.__typeName="Boolean";Boolean.parse=function(a){return a.toLowerCase()=="true"};Number.__typeName="Number";Number.parse=function(a){return!a||!a.length?0:a.indexOf(".")>=0||a.indexOf("e")>=0||a.endsWith("f")||a.endsWith("F")?parseFloat(a):parseInt(a,10)};Number.prototype.format=function(a){return ss.isNullOrUndefined(a)||a.length==0||a=="i"?this.toString():this._netFormat(a,false)};Number.prototype.localeFormat=function(a){return ss.isNullOrUndefined(a)||a.length==0||a=="i"?this.toLocaleString():this._netFormat(a,true)};Number._commaFormat=function(a,i,n,o){var c=null,h=a.indexOf(n);if(h>0){c=a.substr(h);a=a.substr(0,h)}var j=a.startsWith("-");if(j)a=a.substr(1);var f=0,g=i[f];if(a.length<g)return c?a+c:a;var k=a.length,b="",l=false;while(!l){var e=g,d=k-e;if(d<0){g+=d;e+=d;d=0;l=true}if(!e)break;var m=a.substr(d,e);if(b.length)b=m+o+b;else b=m;k-=e;if(f<i.length-1){f++;g=i[f]}}if(j)b="-"+b;return c?b+c:b};Number.prototype._netFormat=function(f,g){var b=g?ss.CultureInfo.CurrentCulture.numberFormat:ss.CultureInfo.InvariantCulture.numberFormat,a="",c=-1;if(f.length>1)c=parseInt(f.substr(1));var e=f.charAt(0);switch(e){case"d":case"D":a=parseInt(Math.abs(this)).toString();if(c!=-1)a=a.padLeft(c,"0");if(this<0)a="-"+a;break;case"x":case"X":a=parseInt(Math.abs(this)).toString(16);if(e=="X")a=a.toUpperCase();if(c!=-1)a=a.padLeft(c,"0");break;case"e":case"E":if(c==-1)a=this.toExponential();else a=this.toExponential(c);if(e=="E")a=a.toUpperCase();break;case"f":case"F":case"n":case"N":if(c==-1)c=b.numberDecimalDigits;a=this.toFixed(c).toString();if(c&&b.numberDecimalSeparator!="."){var d=a.indexOf(".");a=a.substr(0,d)+b.numberDecimalSeparator+a.substr(d+1)}if(e=="n"||e=="N")a=Number._commaFormat(a,b.numberGroupSizes,b.numberDecimalSeparator,b.numberGroupSeparator);break;case"c":case"C":if(c==-1)c=b.currencyDecimalDigits;a=Math.abs(this).toFixed(c).toString();if(c&&b.currencyDecimalSeparator!="."){var d=a.indexOf(".");a=a.substr(0,d)+b.currencyDecimalSeparator+a.substr(d+1)}a=Number._commaFormat(a,b.currencyGroupSizes,b.currencyDecimalSeparator,b.currencyGroupSeparator);if(this<0)a=String.format(b.currencyNegativePattern,a);else a=String.format(b.currencyPositivePattern,a);break;case"p":case"P":if(c==-1)c=b.percentDecimalDigits;a=(Math.abs(this)*100).toFixed(c).toString();if(c&&b.percentDecimalSeparator!="."){var d=a.indexOf(".");a=a.substr(0,d)+b.percentDecimalSeparator+a.substr(d+1)}a=Number._commaFormat(a,b.percentGroupSizes,b.percentDecimalSeparator,b.percentGroupSeparator);if(this<0)a=String.format(b.percentNegativePattern,a);else a=String.format(b.percentPositivePattern,a)}return a};String.__typeName="String";String.Empty="";String.compare=function(a,b,c){if(c){if(a)a=a.toUpperCase();if(b)b=b.toUpperCase()}a=a||"";b=b||"";return a==b?0:a<b?-1:1};String.prototype.compareTo=function(b,a){return String.compare(this,b,a)};String.concat=function(){return arguments.length===2?arguments[0]+arguments[1]:Array.prototype.join.call(arguments,"")};String.prototype.endsWith=function(a){return!a.length?true:a.length>this.length?false:this.substr(this.length-a.length)==a};String.equals=function(b,c,a){return String.compare(b,c,a)==0};String._format=function(b,c,a){if(!String._formatRE)String._formatRE=/(\{[^\}^\{]+\})/g;return b.replace(String._formatRE,function(h,d){var g=parseInt(d.substr(1)),b=c[g+1];if(ss.isNullOrUndefined(b))return"";if(b.format){var e=null,f=d.indexOf(":");if(f>0)e=d.substring(f+1,d.length-1);return a?b.localeFormat(e):b.format(e)}else return a?b.toLocaleString():b.toString()})};String.format=function(a){return String._format(a,arguments,false)};String.fromChar=function(a,d){for(var c=a,b=1;b<d;b++)c+=a;return c};String.prototype.htmlDecode=function(){var a=document.createElement("div");a.innerHTML=this;return a.textContent||a.innerText};String.prototype.htmlEncode=function(){var a=document.createElement("div");a.appendChild(document.createTextNode(this));return a.innerHTML.replace(/\"/g,"&quot;")};String.prototype.indexOfAny=function(f,a,e){var b=this.length;if(!b)return-1;a=a||0;e=e||b;var d=a+e-1;if(d>=b)d=b-1;for(var c=a;c<=d;c++)if(f.indexOf(this.charAt(c))>=0)return c;return-1};String.prototype.insert=function(a,b){if(!b)return this.valueOf();if(!a)return b+this;var c=this.substr(0,a),d=this.substr(a);return c+b+d};String.isNullOrEmpty=function(a){return!a||!a.length};String.prototype.lastIndexOfAny=function(f,a,e){var d=this.length;if(!d)return-1;a=a||d-1;e=e||d;var c=a-e+1;if(c<0)c=0;for(var b=a;b>=c;b--)if(f.indexOf(this.charAt(b))>=0)return b;return-1};String.localeFormat=function(a){return String._format(a,arguments,true)};String.prototype.padLeft=function(b,a){if(this.length<b){a=a||" ";return String.fromChar(a,b-this.length)+this}return this.valueOf()};String.prototype.padRight=function(b,a){if(this.length<b){a=a||" ";return this+String.fromChar(a,b-this.length)}return this.valueOf()};String.prototype.remove=function(a,b){return!b||a+b>this.length?this.substr(0,a):this.substr(0,a)+this.substr(a+b)};String.prototype.replaceAll=function(b,a){a=a||"";return this.split(b).join(a)};String.prototype.startsWith=function(a){return!a.length?true:a.length>this.length?false:this.substr(0,a.length)==a};if(!String.prototype.trim)String.prototype.trim=function(){return this.trimEnd().trimStart()};String.prototype.trimEnd=function(){return this.replace(/\s*$/,"")};String.prototype.trimStart=function(){return this.replace(/^\s*/,"")};Array.__typeName="Array";Array.__interfaces=[ss.IEnumerable];Array.prototype.add=function(a){this[this.length]=a};Array.prototype.addRange=function(a){this.push.apply(this,a)};Array.prototype.aggregate=function(b,c,d){for(var e=this.length,a=0;a<e;a++)if(a in this)b=c.call(d,b,this[a],a,this);return b};Array.prototype.clear=function(){this.length=0};Array.prototype.clone=function(){return this.length===1?[this[0]]:Array.apply(null,this)};Array.prototype.contains=function(b){var a=this.indexOf(b);return a>=0};Array.prototype.dequeue=function(){return this.shift()};Array.prototype.enqueue=function(a){this._queue=true;this.push(a)};Array.prototype.peek=function(){if(this.length){var a=this._queue?0:this.length-1;return this[a]}return null};if(!Array.prototype.every)Array.prototype.every=function(b,c){for(var d=this.length,a=0;a<d;a++)if(a in this&&!b.call(c,this[a],a,this))return false;return true};Array.prototype.extract=function(a,b){return!b?this.slice(a):this.slice(a,a+b)};if(!Array.prototype.filter)Array.prototype.filter=function(d,e){for(var f=this.length,b=[],a=0;a<f;a++)if(a in this){var c=this[a];d.call(e,c,a,this)&&b.push(c)}return b};if(!Array.prototype.forEach)Array.prototype.forEach=function(b,c){for(var d=this.length,a=0;a<d;a++)a in this&&b.call(c,this[a],a,this)};Array.prototype.getEnumerator=function(){return new ss.ArrayEnumerator(this)};Array.prototype.groupBy=function(f,g){for(var h=this.length,d=[],e={},b=0;b<h;b++)if(b in this){var c=f.call(g,this[b],b);if(String.isNullOrEmpty(c))continue;var a=e[c];if(!a){a=[];a.key=c;e[c]=a;d.add(a)}a.add(this[b])}return d};Array.prototype.index=function(d,e){for(var f=this.length,b={},a=0;a<f;a++)if(a in this){var c=d.call(e,this[a],a);if(String.isNullOrEmpty(c))continue;b[c]=this[a]}return b};if(!Array.prototype.indexOf)Array.prototype.indexOf=function(d,b){b=b||0;var c=this.length;if(c)for(var a=b;a<c;a++)if(this[a]===d)return a;return-1};Array.prototype.insert=function(a,b){this.splice(a,0,b)};Array.prototype.insertRange=function(c,b){if(c===0)this.unshift.apply(this,b);else for(var a=0;a<b.length;a++)this.splice(c+a,0,b[a])};if(!Array.prototype.map)Array.prototype.map=function(d,e){for(var b=this.length,c=new Array(b),a=0;a<b;a++)if(a in this)c[a]=d.call(e,this[a],a,this);return c};Array.parse=function(a){return eval("("+a+")")};Array.prototype.remove=function(b){var a=this.indexOf(b);if(a>=0){this.splice(a,1);return true}return false};Array.prototype.removeAt=function(a){this.splice(a,1)};Array.prototype.removeRange=function(b,a){return this.splice(b,a)};if(!Array.prototype.some)Array.prototype.some=function(b,c){for(var d=this.length,a=0;a<d;a++)if(a in this&&b.call(c,this[a],a,this))return true;return false};Array.toArray=function(a){return Array.prototype.slice.call(a)};RegExp.__typeName="RegExp";RegExp.parse=function(a){if(a.startsWith("/")){var b=a.lastIndexOf("/");if(b>1){var c=a.substring(1,b),d=a.substr(b+1);return new RegExp(c,d)}}return null};Date.__typeName="Date";Date.empty=null;Date.get_now=function(){return new Date};Date.get_today=function(){var a=new Date;return new Date(a.getFullYear(),a.getMonth(),a.getDate())};Date.isEmpty=function(a){return a===null||a.valueOf()===0};Date.prototype.format=function(a){return ss.isNullOrUndefined(a)||a.length==0||a=="i"?this.toString():a=="id"?this.toDateString():a=="it"?this.toTimeString():this._netFormat(a,false)};Date.prototype.localeFormat=function(a){return ss.isNullOrUndefined(a)||a.length==0||a=="i"?this.toLocaleString():a=="id"?this.toLocaleDateString():a=="it"?this.toLocaleTimeString():this._netFormat(a,true)};Date.prototype._netFormat=function(d,i){var b=this,c=i?ss.CultureInfo.CurrentCulture.dateFormat:ss.CultureInfo.InvariantCulture.dateFormat;if(d.length==1)switch(d){case"f":d=c.longDatePattern+" "+c.shortTimePattern;break;case"F":d=c.dateTimePattern;break;case"d":d=c.shortDatePattern;break;case"D":d=c.longDatePattern;break;case"t":d=c.shortTimePattern;break;case"T":d=c.longTimePattern;break;case"g":d=c.shortDatePattern+" "+c.shortTimePattern;break;case"G":d=c.shortDatePattern+" "+c.longTimePattern;break;case"R":case"r":c=ss.CultureInfo.InvariantCulture.dateFormat;d=c.gmtDateTimePattern;break;case"u":d=c.universalDateTimePattern;break;case"U":d=c.dateTimePattern;b=new Date(b.getUTCFullYear(),b.getUTCMonth(),b.getUTCDate(),b.getUTCHours(),b.getUTCMinutes(),b.getUTCSeconds(),b.getUTCMilliseconds());break;case"s":d=c.sortableDateTimePattern}if(d.charAt(0)=="%")d=d.substr(1);if(!Date._formatRE)Date._formatRE=/'.*?[^\\]'|dddd|ddd|dd|d|MMMM|MMM|MM|M|yyyy|yy|y|hh|h|HH|H|mm|m|ss|s|tt|t|fff|ff|f|zzz|zz|z/g;var g=Date._formatRE,h=new ss.StringBuilder;g.lastIndex=0;while(true){var j=g.lastIndex,f=g.exec(d);h.append(d.slice(j,f?f.index:d.length));if(!f)break;var e=f[0],a=e;switch(e){case"dddd":a=c.dayNames[b.getDay()];break;case"ddd":a=c.shortDayNames[b.getDay()];break;case"dd":a=b.getDate().toString().padLeft(2,"0");break;case"d":a=b.getDate();break;case"MMMM":a=c.monthNames[b.getMonth()];break;case"MMM":a=c.shortMonthNames[b.getMonth()];break;case"MM":a=(b.getMonth()+1).toString().padLeft(2,"0");break;case"M":a=b.getMonth()+1;break;case"yyyy":a=b.getFullYear();break;case"yy":a=(b.getFullYear()%100).toString().padLeft(2,"0");break;case"y":a=b.getFullYear()%100;break;case"h":case"hh":a=b.getHours()%12;if(!a)a="12";else if(e=="hh")a=a.toString().padLeft(2,"0");break;case"HH":a=b.getHours().toString().padLeft(2,"0");break;case"H":a=b.getHours();break;case"mm":a=b.getMinutes().toString().padLeft(2,"0");break;case"m":a=b.getMinutes();break;case"ss":a=b.getSeconds().toString().padLeft(2,"0");break;case"s":a=b.getSeconds();break;case"t":case"tt":a=b.getHours()<12?c.amDesignator:c.pmDesignator;if(e=="t")a=a.charAt(0);break;case"fff":a=b.getMilliseconds().toString().padLeft(3,"0");break;case"ff":a=b.getMilliseconds().toString().padLeft(3).substr(0,2);break;case"f":a=b.getMilliseconds().toString().padLeft(3).charAt(0);break;case"z":a=b.getTimezoneOffset()/60;a=(a>=0?"-":"+")+Math.floor(Math.abs(a));break;case"zz":case"zzz":a=b.getTimezoneOffset()/60;a=(a>=0?"-":"+")+Math.floor(Math.abs(a)).toString().padLeft(2,"0");if(e=="zzz")a+=c.timeSeparator+Math.abs(b.getTimezoneOffset()%60).toString().padLeft(2,"0");break;default:if(a.charAt(0)=="'")a=a.substr(1,a.length-2).replace(/\\'/g,"'")}h.append(a)}return h.toString()};Date.parseDate=function(a){return new Date(Date.parse(a))};Error.__typeName="Error";Error.prototype.popStackFrame=function(){if(ss.isNullOrUndefined(this.stack)||ss.isNullOrUndefined(this.fileName)||ss.isNullOrUndefined(this.lineNumber))return;var a=this.stack.split("\n"),c=a[0],e=this.fileName+":"+this.lineNumber;while(!ss.isNullOrUndefined(c)&&c.indexOf(e)===-1){a.shift();c=a[0]}var d=a[1];if(isNullOrUndefined(d))return;var b=d.match(/@(.*):(\d+)$/);if(ss.isNullOrUndefined(b))return;a.shift();this.stack=a.join("\n");this.fileName=b[1];this.lineNumber=parseInt(b[2])};Error.createError=function(e,b,c){var a=new Error(e);if(b)for(var d in b)a[d]=b[d];if(c)a.innerException=c;a.popStackFrame();return a};ss.Debug=window.Debug||function(){};ss.Debug.__typeName="Debug";if(!ss.Debug.writeln)ss.Debug.writeln=function(a){if(window.console){if(window.console.debug){window.console.debug(a);return}else if(window.console.log){window.console.log(a);return}}else if(window.opera&&window.opera.postError){window.opera.postError(a);return}};ss.Debug._fail=function(a){ss.Debug.writeln(a);eval("debugger;")};ss.Debug.assert=function(b,a){if(!b){a="Assert failed: "+a;confirm(a+"\r\n\r\nBreak into debugger?")&&ss.Debug._fail(a)}};ss.Debug.fail=function(a){ss.Debug._fail(a)};window.Type=Function;Type.__typeName="Type";window.__Namespace=function(a){this.__typeName=a};__Namespace.prototype={__namespace:true,getName:function(){return this.__typeName}};Type.registerNamespace=function(e){if(!window.__namespaces)window.__namespaces={};if(!window.__rootNamespaces)window.__rootNamespaces=[];if(window.__namespaces[e])return;for(var c=window,d=e.split("."),a=0;a<d.length;a++){var f=d[a],b=c[f];if(!b){c[f]=b=new __Namespace(d.slice(0,a+1).join("."));a==0&&window.__rootNamespaces.add(b)}c=b}window.__namespaces[e]=c};Type.prototype.registerClass=function(d,c,a){this.prototype.constructor=this;this.__typeName=d;this.__class=true;this.__baseType=c||Object;if(c)this.__basePrototypePending=true;if(a){this.__interfaces=[];for(var b=2;b<arguments.length;b++){a=arguments[b];this.__interfaces.add(a)}}};Type.prototype.registerInterface=function(a){this.__typeName=a;this.__interface=true};Type.prototype.registerEnum=function(c,b){for(var a in this.prototype)this[a]=this.prototype[a];this.__typeName=c;this.__enum=true;if(b)this.__flags=true};Type.prototype.setupBase=function(){if(this.__basePrototypePending){var a=this.__baseType;a.__basePrototypePending&&a.setupBase();for(var b in a.prototype){var c=a.prototype[b];if(!this.prototype[b])this.prototype[b]=c}delete this.__basePrototypePending}};if(!Type.prototype.resolveInheritance)Type.prototype.resolveInheritance=Type.prototype.setupBase;Type.prototype.initializeBase=function(a,b){this.__basePrototypePending&&this.setupBase();if(!b)this.__baseType.apply(a);else this.__baseType.apply(a,b)};Type.prototype.callBaseMethod=function(b,d,c){var a=this.__baseType.prototype[d];return!c?a.apply(b):a.apply(b,c)};Type.prototype.get_baseType=function(){return this.__baseType||null};Type.prototype.get_fullName=function(){return this.__typeName};Type.prototype.get_name=function(){var a=this.__typeName,b=a.lastIndexOf(".");return b>0?a.substr(b+1):a};Type.prototype.getInterfaces=function(){return this.__interfaces};Type.prototype.isInstanceOfType=function(a){if(ss.isNullOrUndefined(a))return false;if(this==Object||a instanceof this)return true;var b=Type.getInstanceType(a);return this.isAssignableFrom(b)};Type.prototype.isAssignableFrom=function(c){if(this==Object||this==c)return true;if(this.__class){var a=c.__baseType;while(a){if(this==a)return true;a=a.__baseType}}else if(this.__interface){var b=c.__interfaces;if(b&&b.contains(this))return true;var a=c.__baseType;while(a){b=a.__interfaces;if(b&&b.contains(this))return true;a=a.__baseType}}return false};Type.isClass=function(a){return a.__class==true};Type.isEnum=function(a){return a.__enum==true};Type.isFlags=function(a){return a.__enum==true&&a.__flags==true};Type.isInterface=function(a){return a.__interface==true};Type.isNamespace=function(a){return a.__namespace==true};Type.canCast=function(a,b){return b.isInstanceOfType(a)};Type.safeCast=function(a,b){return b.isInstanceOfType(a)?a:null};Type.getInstanceType=function(b){var a=null;try{a=b.constructor}catch(c){}if(!a||!a.__typeName)a=Object;return a};Type.getType=function(a){if(!a)return null;if(!Type.__typeCache)Type.__typeCache={};var b=Type.__typeCache[a];if(!b){b=eval(a);Type.__typeCache[a]=b}return b};Type.parse=function(a){return Type.getType(a)};ss.Delegate=function(){};ss.Delegate.registerClass("Delegate");ss.Delegate.empty=function(){};ss.Delegate._contains=function(b,d,c){for(var a=0;a<b.length;a+=2)if(b[a]===d&&b[a+1]===c)return true;return false};ss.Delegate._create=function(a){var b=function(){if(a.length==2)return a[1].apply(a[0],arguments);else{for(var c=a.clone(),b=0;b<c.length;b+=2)ss.Delegate._contains(a,c[b],c[b+1])&&c[b+1].apply(c[b],arguments);return null}};b._targets=a;return b};ss.Delegate.create=function(b,a){return!b?a:ss.Delegate._create([b,a])};ss.Delegate.combine=function(a,b){if(!a)return!b._targets?ss.Delegate.create(null,b):b;if(!b)return!a._targets?ss.Delegate.create(null,a):a;var c=a._targets?a._targets:[null,a],d=b._targets?b._targets:[null,b];return ss.Delegate._create(c.concat(d))};ss.Delegate.remove=function(c,a){if(!c||c===a)return null;if(!a)return c;var b=c._targets,f=null,e;if(a._targets){f=a._targets[0];e=a._targets[1]}else e=a;for(var d=0;d<b.length;d+=2)if(b[d]===f&&b[d+1]===e){if(b.length==2)return null;b.splice(d,2);return ss.Delegate._create(b)}return c};ss.Delegate.createExport=function(b,c,a){a=a||"__"+(new Date).valueOf();window[a]=c?b:function(){try{delete window[a]}catch(c){window[a]=undefined}b.apply(null,arguments)};return a};ss.Delegate.deleteExport=function(a){delete window[a]};ss.Delegate.clearExport=function(a){window[a]=ss.Delegate.empty};ss.CultureInfo=function(c,a,b){this.name=c;this.numberFormat=a;this.dateFormat=b};ss.CultureInfo.registerClass("CultureInfo");ss.CultureInfo.InvariantCulture=new ss.CultureInfo("en-US",{naNSymbol:"NaN",negativeSign:"-",positiveSign:"+",negativeInfinityText:"-Infinity",positiveInfinityText:"Infinity",percentSymbol:"%",percentGroupSizes:[3],percentDecimalDigits:2,percentDecimalSeparator:".",percentGroupSeparator:",",percentPositivePattern:"{0} %",percentNegativePattern:"-{0} %",currencySymbol:"$",currencyGroupSizes:[3],currencyDecimalDigits:2,currencyDecimalSeparator:".",currencyGroupSeparator:",",currencyNegativePattern:"(${0})",currencyPositivePattern:"${0}",numberGroupSizes:[3],numberDecimalDigits:2,numberDecimalSeparator:".",numberGroupSeparator:","},{amDesignator:"AM",pmDesignator:"PM",dateSeparator:"/",timeSeparator:":",gmtDateTimePattern:"ddd, dd MMM yyyy HH:mm:ss 'GMT'",universalDateTimePattern:"yyyy-MM-dd HH:mm:ssZ",sortableDateTimePattern:"yyyy-MM-ddTHH:mm:ss",dateTimePattern:"dddd, MMMM dd, yyyy h:mm:ss tt",longDatePattern:"dddd, MMMM dd, yyyy",shortDatePattern:"M/d/yyyy",longTimePattern:"h:mm:ss tt",shortTimePattern:"h:mm tt",firstDayOfWeek:0,dayNames:["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"],shortDayNames:["Sun","Mon","Tue","Wed","Thu","Fri","Sat"],minimizedDayNames:["Su","Mo","Tu","We","Th","Fr","Sa"],monthNames:["January","February","March","April","May","June","July","August","September","October","November","December",""],shortMonthNames:["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec",""]});ss.CultureInfo.CurrentCulture=ss.CultureInfo.InvariantCulture;ss.IEnumerator=function(){};ss.IEnumerator.getEnumerator=function(a){return a?a.getEnumerator?a.getEnumerator():new ss.ArrayEnumerator(a):null};ss.IEnumerator.registerInterface("IEnumerator");ss.IEnumerable=function(){};ss.IEnumerable.registerInterface("IEnumerable");ss.ArrayEnumerator=function(a){this._array=a;this._index=-1;this.current=null};ss.ArrayEnumerator.prototype={moveNext:function(){this._index++;this.current=this._array[this._index];return this._index<this._array.length},reset:function(){this._index=-1;this.current=null}};ss.ArrayEnumerator.registerClass("ArrayEnumerator",null,ss.IEnumerator);ss.IDisposable=function(){};ss.IDisposable.registerInterface("IDisposable");ss.StringBuilder=function(a){this._parts=ss.isNullOrUndefined(a)||a===""?[]:[a];this.isEmpty=this._parts.length==0};ss.StringBuilder.prototype={append:function(a){if(!ss.isNullOrUndefined(a)&&a!==""){this._parts.add(a);this.isEmpty=false}return this},appendLine:function(a){this.append(a);this.append("\r\n");this.isEmpty=false;return this},clear:function(){this._parts=[];this.isEmpty=true},toString:function(a){return this._parts.join(a||"")}};ss.StringBuilder.registerClass("StringBuilder");ss.EventArgs=function(){};ss.EventArgs.registerClass("EventArgs");ss.EventArgs.Empty=new ss.EventArgs;if(!window.XMLHttpRequest)window.XMLHttpRequest=function(){for(var b=["Msxml2.XMLHTTP","Microsoft.XMLHTTP"],a=0;a<b.length;a++)try{return new ActiveXObject(b[a])}catch(d){}return null};ss.parseXml=function(d){try{if(DOMParser){var e=new DOMParser;return e.parseFromString(d,"text/xml")}else for(var c=["Msxml2.DOMDocument.3.0","Msxml2.DOMDocument"],b=0;b<c.length;b++){var a=new ActiveXObject(c[b]);a.async=false;a.loadXML(d);a.setProperty("SelectionLanguage","XPath");return a}}catch(f){}return null};ss.CancelEventArgs=function(){ss.CancelEventArgs.initializeBase(this);this.cancel=false};ss.CancelEventArgs.registerClass("CancelEventArgs",ss.EventArgs);ss.Tuple=function(b,a,c){this.first=b;this.second=a;if(arguments.length==3)this.third=c};ss.Tuple.registerClass("Tuple");ss.Observable=function(a){this._v=a;this._observers=null};ss.Observable.prototype={getValue:function(){this._observers=ss.Observable._captureObservers(this._observers);return this._v},setValue:function(b){if(this._v!==b){this._v=b;var a=this._observers;if(a){this._observers=null;ss.Observable._invalidateObservers(a)}}}};ss.Observable._observerStack=[];ss.Observable._observerRegistration={dispose:function(){ss.Observable._observerStack.pop()}};ss.Observable.registerObserver=function(a){ss.Observable._observerStack.push(a);return ss.Observable._observerRegistration};ss.Observable._captureObservers=function(a){var c=ss.Observable._observerStack,d=c.length;if(d){a=a||[];for(var b=0;b<d;b++){var e=c[b];!a.contains(e)&&a.push(e)}return a}return null};ss.Observable._invalidateObservers=function(b){for(var a=0,c=b.length;a<c;a++)b[a].invalidateObserver()};ss.Observable.registerClass("Observable");ss.ObservableCollection=function(a){this._items=a||[];this._observers=null};ss.ObservableCollection.prototype={get_item:function(a){this._observers=ss.Observable._captureObservers(this._observers);return this._items[a]},set_item:function(a,b){this._items[a]=b;this._updated()},get_length:function(){this._observers=ss.Observable._captureObservers(this._observers);return this._items.length},add:function(a){this._items.push(a);this._updated()},clear:function(){this._items.clear();this._updated()},contains:function(a){return this._items.contains(a)},getEnumerator:function(){this._observers=ss.Observable._captureObservers(this._observers);return this._items.getEnumerator()},indexOf:function(a){return this._items.indexOf(a)},insert:function(a,b){this._items.insert(a,b);this._updated()},remove:function(a){if(this._items.remove(a)){this._updated();return true}return false},removeAt:function(a){this._items.removeAt(a);this._updated()},toArray:function(){return this._items},_updated:function(){var a=this._observers;if(a){this._observers=null;ss.Observable._invalidateObservers(a)}}};ss.ObservableCollection.registerClass("ObservableCollection",null,ss.IEnumerable);ss.IApplication=function(){};ss.IApplication.registerInterface("IApplication");ss.IContainer=function(){};ss.IContainer.registerInterface("IContainer");ss.IObjectFactory=function(){};ss.IObjectFactory.registerInterface("IObjectFactory");ss.IEventManager=function(){};ss.IEventManager.registerInterface("IEventManager");ss.IInitializable=function(){};ss.IInitializable.registerInterface("IInitializable")
/** GUIDManager.js **/
function GUIDManager(aras) {
	this.aras = aras;
	this.storage = [];
	// count of guids that request from server by default
	this.count = 100;
}

//calls guid service method that return new guid
GUIDManager.prototype.GetGUID = function GUIDManagerGetGUID() {
	if (!this.storage.length) {
		GetGuidsFromServer(this, this.count);
		this.count = this.count * 2;
	}
	return this.storage.pop();

};
//gets new GUIDs for InnovatorServer
function GetGuidsFromServer(guidMgr, count) {
	var res = guidMgr.aras.soapSend('generateNewGUIDEx', '<Item quantity=\'' + count + '\'/>');
	if (0 !== res.getFaultCode()) {
		guidMgr.aras.AlertError(res);
		var resIOMError = guidMgr.aras.newIOMInnovator().newError(res.getFaultString());
		return resIOMError;
	}
	res = res.getResult();
	guidMgr.RefreshDataInStorage(res);
}

//adds new GUIDs in storage
GUIDManager.prototype.RefreshDataInStorage = function GUIDManagerRefreshDataInStack(source) {
	if (!source) {
		return;
	}
	var propIds = source.selectSingleNode('ids').text;
	var guids = propIds.split(';');
	this.storage = this.storage.concat(guids);
};

/** FileUpload.js **/
function FileUpload(aras, uri) {
	this._aras = aras;
	this._uri = uri;
}

FileUpload.prototype.uploadFiles = function FileUpload_uploadFiles(fileList, clientData, async) {
	var $Promise = async ? Promise : ArasModules.SyncPromise;

	this._aras.vault.clearClientData();
	for (var i = 0; i < clientData.length; i++) {
		this._aras.vault.setClientData(clientData[i].get_name(), clientData[i].get_value());
	}

	this._aras.vault.clearFileList();
	for (var fileId in fileList) {
		this._aras.vault.addFileToList(fileId, fileList[fileId]);
	}

	var response;
	var promise = (async ? this._aras.vault.sendFilesAsync(this._uri) : $Promise.resolve(this._aras.vault.sendFiles(this._uri))).then(function(resolve) {
		response = this._aras.vault.getResponse();

		if (!resolve || !response) {
			this._aras.AlertError(this._aras.getResource('', 'item_methods_ex.failed_upload_file', this._uri));
			if (!resolve) {
				response += this._aras.vault.getLastError();
			}
			this._aras.AlertError(this._aras.getResource('', 'item_methods_ex.internal_error_occured'), resolve + '\n' + response, this._aras.getResource('', 'common.client_side_err'));
			response = null;
		}

		return response;
	}.bind(this));

	return async ? promise : response;
};

/** FileDownload.js **/
var FileDownload = {
	downloadFile: function(fileUrl, filePath, headers) {
		var vault = aras.vault;

		vault.clearClientData();
		vault.clearFileList();

		vault.setClientData('SOAPACTION', 'GetFile');
		headers.forEach(function(headder) {
			if (headder.get_name() && headder.get_value()) {
				vault.setClientData(headder.get_name(), headder.get_value());
			}
		});

		var fileName = filePath.replace(/^.*[\\\/]/, '');
		vault.setLocalFileName(fileName);

		if (!vault.downloadFile(fileUrl)) {
			aras.AlertError(aras.getResource('', 'item_window.failed_download_file'), 'item_window: ' + vault.getLastError(), aras.getResource('', 'common.client_side_err'));
		}
		return true;
	}
};

/** EasyFileInfo.js **/
function EasyFileInfo(vault) {
	this._vault = vault;
}

EasyFileInfo.prototype.getFileChecksum = function EasyFileInfoGetFileChecksum(fileName) {
	return this._vault.getFileChecksum(fileName);
};

EasyFileInfo.prototype.getFileSize = function EasyFileInfoGetFileSize(fileName) {
	return this._vault.getFileSize(fileName);
};

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

/** ..\Modules\aras.innovator.core.MainWindow\setup.js **/
(function() {
	var containerWidget = null;
	var rm;
	var splitter;
	let initTocPromise = null;

	function initializeTocTree() {
		const sidebar = document.getElementById('navigationPanel');
		const mainTreeApplet = sidebar.nav;
		mainTreeApplet.data = new Map();
		initTocPromise = window.cuiToc(mainTreeApplet, 'TOC')
			.then(selectStartPage)
			.then(function() {
				return initContextMenu(sidebar.popupMenu);
			})
			.then(function() {
				initTocPromise = null;
			});
		return mainTreeApplet;
	}

	function selectStartPage() {
		const userNd = aras.getLoggedUserItem();
		const startingPage = aras.getItemProperty(userNd, 'starting_page');
		const tmpPage = aras.evalMethod('selectStartPage', '');
		const itemTypeId = aras.getItemTypeId(tmpPage || startingPage);

		if (itemTypeId) {
			mainTreeApplet.data.forEach(function(value, key) {
				if (!mainTreeApplet.selected && itemTypeId === value.itemTypeId) {
					mainTreeApplet.expand(key, true);
					mainTreeApplet.select(key);
					mainTreeApplet
						.querySelector('[data-key="' + key + '"] .aras-nav-leaf-ico')
						.dispatchEvent(new CustomEvent('click', {bubbles: true}));
				}
			});
		}

		const searchParams = new URLSearchParams(window.location.search.substr(1, window.location.search.length));
		const startItemStr = searchParams.get('StartItem');
		if (startItemStr) {
			const startItemSetting = startItemStr.split(':');
			aras.evalMethod('runStartPage', '', {
				'itemID': startItemSetting[1],
				'itemTypeName': startItemSetting[0],
				'versionModificator': startItemSetting[2]
			});
		}
	}

	function initContextMenu(contextMenu) {
		return window.cuiContextMenu(contextMenu, 'PopupMenuMainWindowTOC').then(function(cuiContextMenu) {
			mainTreeApplet.on('contextmenu', function(itemKey, event) {
				event.preventDefault();
				event.stopPropagation();
				mainTreeApplet.select(itemKey).then(function() {
					const dataItem = mainTreeApplet.data.get(itemKey);
					cuiContextMenu.show({x: event.clientX, y: event.clientY}, {currentTarget: dataItem});
				});
			});
		});
	}

	window.updateTree = function() {
		if (initTocPromise) {
			return;
		}
		aras.MetadataCache.DeleteConfigurableUiDatesFromCache();
		initTocPromise = window.cuiToc(mainTreeApplet, 'TOC').then(function() {
			document.getElementById('navigationPanel').render();
			initTocPromise = null;
		});
	};

	window.initSvgManager = function() {
		ArasModules.SvgManager.load([
			'../images/PinnedOff.svg',
			'../images/PinnedOn.svg',
			'../images/GridSearch.svg',
			'../images/CreateItem.svg',
			'../images/ExecuteSearch.svg',
			'../images/OpenInTab.svg',
			'../images/BackFull.svg',
			'../images/FavoriteOn.svg',
			'../images/FavoriteOff.svg',
			'../images/ToastError.svg',
			'../images/ToastInfo.svg',
			'../images/ToastSuccess.svg',
			'../images/ToastWarning.svg'
		]);
	};

	window.registerShortcutsAtMainWindowLocation = function(settings, itemTypeName, itemType) {
		if (settings) {
			var loadParams = {
				locationName: 'MainWindowShortcuts',
				'item_classification': '%all_grouped_by_classification%',
				itemTypeName: itemTypeName,
				itemType: itemType
			};

			window.cui.loadShortcutsFromCommandBarsAsync(loadParams, settings);
		}
	};

	function checkCachingMechanism() {
		var checkCachingMechanismUrl = aras.getScriptsURL() + 'CheckCachingMechanism.aspx';
		var requestSettings = {
			url: checkCachingMechanismUrl,
			restMethod: 'GET',
			async: true
		};

		var firstRequestResponse;

		return ArasModules.soap('', requestSettings)
			.then(function(responseText) {
				firstRequestResponse = responseText;

				return ArasModules.soap('', requestSettings);
			})
			.then(function(secondRequestResponse) {

				return firstRequestResponse === secondRequestResponse;
			});
	}

	function disableFileDrop() {
		// disable drop file by all iframes in the window
		var prevent = function(e) {
			e.preventDefault();
		};
		// disable drag&drop for Innovator iframes
		// to prevent an attempt to open a dropped file in a browser
		// so as not to replace the Innovator itself
		[].forEach.call(window.document.querySelectorAll('#tz, #deepLinking, #dimmer_spinner'), function(elm) {
			elm.contentWindow.addEventListener('drop', prevent);
			elm.contentWindow.addEventListener('dragover', prevent);
		});

		// disable drop file by window
		window.addEventListener('drop', prevent);
		window.addEventListener('dragover', prevent);
	}

	window.onLogoutCommand = function(event) {
		if (event) {
			event.preventDefault();
		}

		return new Promise(function(resolve) {
			if (!aras.getCommonPropertyValue('exitInProgress') && window.aras.isDirtyItems()) {
				aras.dirtyItemsHandler();
				resolve();
			} else {
				// Close opened windows to have the same behaviour as in onunload handler.
				// Additionally this call helps to avoid warning that may be shown
				// in onbeforeunload when active tab is not home tab.
				aras.setCommonPropertyValue('exitInProgress', true);
				arasTabs.forceCloseAllTabs();
				aras.getOpenedWindowsCount(true);

				setTimeout(function() {
					// Logout at the first from Innovator.
					aras.logout();
					// And only then from OAuthServer.
					// Call to logout will trigger current document unloading.
					aras.OAuthClient.logout();
					// We should reset onunload handler because all necessary logout logic done here.
					window.onunload = null;
					resolve();
				}, 0);
			}
		});
	};

	window.defineWorkElement = function() {
		Object.defineProperty(window, 'work', {
			configurable: true,
			get: function() {
				const arasTabsObj = window.arasTabs;
				const selectedTabId = arasTabsObj.selectedTab;

				if (!selectedTabId) {
					return window;
				}

				let tabContentWindow;
				const selectedTab = arasTabsObj.data.get(selectedTabId);
				const parentTabId = selectedTab && selectedTab.parentTab;
				if (selectedTabId.startsWith('search_') && window.document.getElementById(selectedTabId)) {
					tabContentWindow = window.document.getElementById(selectedTabId).contentWindow;
				} else if (parentTabId && parentTabId.startsWith('search_') && window.document.getElementById(parentTabId)) {
					tabContentWindow = window.document.getElementById(parentTabId).contentWindow;
				} else if (selectedTab && window.document.getElementById(selectedTabId)) {
					tabContentWindow = window.document.getElementById(selectedTabId).contentWindow;
				}

				return tabContentWindow || window;
			}
		});
	};

	/**
	 * Initialize main window. Called from onSuccessfulLogin function of login.aspx.
	 *
	 * @returns {boolean}
	 */
	window.initialize = function() {
		fixDojoSettings();
		initSvgManager();

		rm = new ResourceManager(new Solution('core'), 'ui_resources.xml', aras.getSessionContextLanguageCode());
		aras.setUserReportServiceBaseUrl(window.location.href.replace(/(\/Client?)(\/|$)(.*)/i, '$1') + '/../SelfServiceReporting');

		var userNd = aras.getLoggedUserItem(true);
		if (!userNd) {
			window.onbeforeunload = '';
			window.close();
			return false;
		}
		if (!document.frames) {
			document.frames = [];
		}

		aras.getPreferenceItemProperty('Core_GlobalLayout', null, 'core_append_items');
		aras.getPreferenceItemProperty('SSVC_Preferences', null, 'default_bookmark');
		aras.getPreferenceItemProperty('ES_Settings', null, 'max_analyzed_chars');

		var update = new InnovatorUpdate();
		update.BeginIsNeedCheckUpdates();

		containerWidget = document.getElementById('main-container');

		defineWorkElement();

		var shortcutSettings = {
			windows: [window],
			context: window
		};

		registerShortcutsAtMainWindowLocation(shortcutSettings);

		checkCachingMechanism()
			.then(function(isCachingMechanismWork) {
				if (!isCachingMechanismWork) {
					aras.AlertError(rm.getString('setup.cache_is_disabled'));
				}
			});

		aras.UpdateFeatureTreeIfNeed();

		document.corporateToLocalOffset = aras.getCorporateToLocalOffset();
		PopulateDocByLabels();

		disableFileDrop();

		window.arasTabs = document.querySelector('aras-header-tabs');
		window.mainTreeApplet = initializeTocTree();

		splitter = document.getElementById('main-container-splitter');
		window.ArasModules.splitter(splitter);
		arasMainWindowInfo.setProvider(new SyncMainWindowInfoProvider());
		return true;
	};
})();

/** ..\Modules\aras.innovator.core.MainWindow\deepLinking.js **/
var deepLinking = (function() {
	var storage;
	let deepLinkingResolve;

	function deepLinkingStorageListener(storageEvent) {
		var changeMessage = function(frame) {
			var win = frame.contentWindow;
			var msg = win.document.getElementById('message');
			if (!msg) {
				frame.addEventListener('load', function() {
					var msg = win.document.getElementById('message');
					msg.textContent = deepLinking.currentMsg;
				});
			} else {
				msg.textContent = deepLinking.currentMsg;
			}
		};

		var setDeepLinkingMessage = function(msg) {
			deepLinking.currentMsg = msg;
			var deepWindowIframe = document.getElementById('deepLinking');
			deepWindowIframe.style.display = 'block';
			document.getElementById('dimmer_spinner').classList.add('aras-hide');
			if (!deepWindowIframe.src) {
				deepWindowIframe.src = 'deepLinking.aspx';
			}
			changeMessage(deepWindowIframe);

			if (deepLinkingResolve) {
				deepLinkingResolve({
					startItemHandled: true
				});
			}
		};

		if (storageEvent.key === 'DeepLinkingMainMenu' && storageEvent.newValue === 'opening') {
			storage.removeItem('DeepLinkingMainMenu');
			setDeepLinkingMessage(aras.getResource('', 'deep_link.start_opening_item'));
		}

		if (storageEvent.key === 'DeepLinkingResultOpenItem' && storageEvent.newValue) {
			storage.removeItem('DeepLinkingResultOpenItem');
			storage.removeItem('DeepLinkingOpenStartItem');
			setDeepLinkingMessage(storageEvent.newValue);
			window.removeEventListener('storage', deepLinkingStorageListener);
		}
	}

	function mainWindowListener(storageEvent) {
		if (storageEvent.key !== 'DeepLinkingOpenStartItem' || !storageEvent.newValue) {
			return;
		}
		var item = JSON.parse(storageEvent.newValue);
		var itemTypeName = item.itemTypeName;
		var itemID = item.itemID;

		if (!itemTypeName || !itemID || !aras.getLoginName || aras.getLoginName() === '') {
			return;
		}

		storage.removeItem('DeepLinkingOpenStartItem');
		storage.removeItem('DeepLinkingResultOpenItem');
		storage.removeItem('DeepLinkingMainMenu');
		storage.setItem('DeepLinkingMainMenu', 'opening');
		var resultOpenItem = aras.evalMethod('runStartPage', '', {
			'itemID': itemID,
			'itemTypeName': itemTypeName,
			'versionModificator': item.versionModificator
		});

		resultOpenItem.then(function(message) {
			storage.setItem('DeepLinkingResultOpenItem', message);
		}).catch(function(message) {
			if (message.stack) {
				message = aras.getResource('', 'common.an_internal_error_has_occured') + ' ' + message.toString();
			}
			storage.setItem('DeepLinkingResultOpenItem', message);
		});
	}

	function getDeepLinkItemData() {
		var itemData = {
			'itemTypeName': null,
			'itemID': null,
			'versionModificator': null
		};
		var searchParams = new URLSearchParams(location.search.substr(1,location.search.length));
		var StartItemStr = searchParams.get('StartItem');
		if (StartItemStr) {
			var arr = StartItemStr.split(':');
			itemData.itemTypeName = arr[0];
			itemData.itemID = arr[1];
			itemData.versionModificator = arr[2];

			if (itemData.itemTypeName && itemData.itemID) {
				return itemData;
			}
		}
	}

	return {
		/*Constant that determines what time DeepLinkingWindow may look MainWindow*/
		SEARCH_TIME_THE_MAIN_WINDOW: 2000,
		currentMsg: '',
		onSuccessfulLogin: function() {
			storage = this.getStorage();
			window.addEventListener('storage', mainWindowListener);
			window.removeEventListener('storage', deepLinkingStorageListener);
		},
		beforeInitializeLoginForm: function() {
			storage = this.getStorage();
			var startItem = getDeepLinkItemData();
			if (startItem) {
				window.addEventListener('storage', deepLinkingStorageListener);
				storage.removeItem('DeepLinkingOpenStartItem');
				storage.setItem('DeepLinkingOpenStartItem', JSON.stringify(startItem));
			}

			window.addEventListener('beforeunload', function() {
				storage.removeItem('DeepLinkingOpenStartItem');
				storage.removeItem('DeepLinkingResultOpenItem');
				storage.removeItem('DeepLinkingMainMenu');
			});

			return new Promise(function(resolve) {
				deepLinkingResolve = resolve;
				if (getDeepLinkItemData()) {
					setTimeout(function() {
						if (this.currentMsg === '') {
							window.removeEventListener('storage', deepLinkingStorageListener);
							resolve({
								startItemHandled: false
							});
						}
						resolve({
							startItemHandled: true
						});
					}.bind(this), this.SEARCH_TIME_THE_MAIN_WINDOW);
				} else {
					resolve({
						startItemHandled: false
					});
				}
			}.bind(this));
		},
		getStorage: function() {
			return window.localStorage;
		}
	};
})();

/** pageReturnBlocker.js **/
var PageReturnBlocker = function() {
	this.completeFlag = 'reloadShortcutsBlocked';
	this.loaderFlag = 'blockerLoaderAttached';
	this.skipFlag = 'skipReloadShortcutsBlocker';
	this.manualStartAttribute = 'startBlockerManually';
	return this;
};

// for current window, prevent default browser behavior for backspace( load previous page ), F5 ( reload current page)
PageReturnBlocker.prototype.attachReloadShortcutsBlocker = function(targetWindow) {
	if (targetWindow && !targetWindow[this.completeFlag] && !targetWindow[this.skipFlag]) {
		var shortcutsBlockHandler = function(evt) {
			var keyCode = evt ? evt.keyCode || evt.which : 0;
			var preventRequired = false;

			switch (keyCode) {
				case 8: //backspace shortcut
					if (targetWindow.document.hasOwnProperty('isEditMode') && !targetWindow.document.isEditMode) {
						preventRequired = true;
					} else {
						var targetElement = evt.target || evt.srcElement;

						if (!targetElement.readOnly && !targetElement.disabled) {
							if (/input/i.test(targetElement.tagName)) {
								preventRequired = !(/text|password|file/i.test(targetElement.type));

							} else if (/textarea/i.test(targetElement.tagName)) {
								preventRequired = false;

							} else {
								preventRequired = !((targetElement.contentEditable === 'true') || (targetElement.ownerDocument.designMode === 'on'));
							}
						} else if (targetElement.readOnly) {
							preventRequired = true;
						}
					}
					break;
				case 116: //F5 shortcut
					preventRequired = true;
			}

			if (preventRequired) {
				evt.preventDefault();
			}
		};

		targetWindow.document.addEventListener('keydown', shortcutsBlockHandler, false);
		targetWindow[this.completeFlag] = true;
	}
};

PageReturnBlocker.prototype.blockInChildFrames = function(targetWindow, blockInChilds) {
	if (targetWindow) {
		var frames = targetWindow.document.querySelectorAll('frame, iframe');
		var currentFrame = null;
		var self = this;

		for (var index = 0; index < frames.length; index++) {
			currentFrame = frames[index];
			if (!currentFrame[this.loaderFlag]) {
				(function(currentFrame) { // jshint ignore:line
					var pageLoadHandler = function() {
						self.attachBlocker(currentFrame.contentWindow, blockInChilds);
					};
					var pageUnloadHandler = function() {
						currentFrame.removeEventListener('load', pageLoadHandler);
						targetWindow.removeEventListener('unload', pageUnloadHandler);
					};
					currentFrame.addEventListener('load', pageLoadHandler, false);
					targetWindow.addEventListener('unload', pageUnloadHandler, false);
				})(currentFrame); // jshint ignore:line

				this.attachBlocker(currentFrame.contentWindow, blockInChilds);
				currentFrame[this.loaderFlag] = true;
			}
		}
	}
};

PageReturnBlocker.prototype.attachBlocker = function(targetWindow, blockInChilds) {
	targetWindow = targetWindow ? targetWindow : window;

	try {
		var doc = targetWindow.document;
	} catch (exe) {
		return;//access denied
	}
	this.attachReloadShortcutsBlocker(targetWindow);

	if (blockInChilds) {
		var documentState = targetWindow.document.readyState;
		if (documentState === 'complete' || documentState === 'interactive') {
			this.blockInChildFrames(targetWindow, true);
		} else {
			var self = this;
			var DOMContentLoadedHandler = function() {
				self.blockInChildFrames(targetWindow, true);
				this.removeEventListener('DOMContentLoaded', DOMContentLoadedHandler);
			};

			targetWindow.document.addEventListener('DOMContentLoaded', DOMContentLoadedHandler, false);
		}
	}
};

// add returnBlocker object to window
var returnBlockerHelper = new PageReturnBlocker();

(function() {
	var blockerScript = null;
	var pageScripts = document.getElementsByTagName('script');
	var scriptSrc = '';

	for (var i = 0; i < pageScripts.length; i++) {
		scriptSrc = pageScripts[i].src.toUpperCase();

		if (scriptSrc.indexOf('PAGERETURNBLOCKER') > -1) {
			blockerScript = pageScripts[i];
			break;
		}
	}

	var startManual = blockerScript.getAttribute(returnBlockerHelper.manualStartAttribute);
	if (startManual != 'true') {
		window.document.addEventListener('DOMContentLoaded', function() { returnBlockerHelper.attachBlocker(null, true); }, false);
	}
})();

/** IOM.ScriptSharp.js **/
// IOM.ScriptSharp.js
(function(){
window.StringComparison=function(){}
window.CompressionType=function(){}
window.RegexOptions=function(){}
window.HttpUtility=function(){}
HttpUtility.urlEncode=function(url){return encodeURIComponent(url);}
Type.registerNamespace('Aras.IOM');Aras.IOM.IServerConnection=function(){};Aras.IOM.IServerConnection.registerInterface('Aras.IOM.IServerConnection');Aras.IOM.FetchFileMode=function(){};Aras.IOM.FetchFileMode.prototype = {normal:0,dry:1}
Aras.IOM.FetchFileMode.registerEnum('Aras.IOM.FetchFileMode',false);Aras.IOM.UrlType=function(){};Aras.IOM.UrlType.prototype = {none:0,securityToken:1}
Aras.IOM.UrlType.registerEnum('Aras.IOM.UrlType',false);Aras.IOM.HttpConnectionParameters=function(){}
Aras.IOM.HttpConnectionParameters.prototype={forceWritableSession:false}
Aras.IOM.I18NSessionContext=function(validateUsrXmlResult){this.$7=new Aras.I18NUtils._I18NConverter();if(String.isNullOrEmpty(validateUsrXmlResult)){return;}var $0=new XmlDocument();var $1;try{$0.loadXML(validateUsrXmlResult);$1=$0.documentElement.selectSingleNode('/*/*/*/i18nsessioncontext');}catch($2){$1=null;}if($1==null){return;}this.$0=Aras.IOM.I18NSessionContext.$8($1,'locale');this.$1=Aras.IOM.I18NSessionContext.$8($1,'language_code');this.$2=Aras.IOM.I18NSessionContext.$8($1,'language_suffix');this.$3=Aras.IOM.I18NSessionContext.$8($1,'default_language_code');this.$4=Aras.IOM.I18NSessionContext.$8($1,'default_language_suffix');this.$5=Aras.IOM.I18NSessionContext.$8($1,'time_zone');this.$6=Aras.IOM.I18NSessionContext.$9($1,'corporate_to_local_offset');}
Aras.IOM.I18NSessionContext.$8=function($p0,$p1){var $0=$p0.selectSingleNode($p1);return ($0==null||!$0.text.trim().length)?null:$0.text.trim();}
Aras.IOM.I18NSessionContext.$9=function($p0,$p1){var $0=Aras.IOM.I18NSessionContext.$8($p0,$p1);var $1=Number.MIN_VALUE;if(!String.isNullOrEmpty($0)){try{$1=parseInt($0);}catch($2){$0=null;}}if(String.isNullOrEmpty($0)&&!String.isNullOrEmpty($p1)){var $3=$p1.toLowerCase();switch($3){case 'time_zone':$1=-1;break;case 'corporate_to_local_offset':$1=0;break;}}return $1;}
Aras.IOM.I18NSessionContext.prototype={$0:null,$1:null,$2:null,$3:null,$4:null,$5:null,$6:0,ConvertToNeutral:function(svalue,vtype,datePtrn){return this.$7.$A(svalue,vtype,true,datePtrn,this.GetLocale(),this.GetTimeZone());},ConvertFromNeutral:function(svalue,vtype,datePtrn){return this.$7.$A(svalue,vtype,false,datePtrn,this.GetLocale(),this.GetTimeZone());},ConvertUtcDateTimeToNeutral:function(utcStr,inPattern){if(utcStr==null){return null;}var $0;var $1=CultureInfo.InvariantCulture.DateTimeFormat;if(String.isNullOrEmpty(inPattern)){$0=$1.Parse(utcStr,null,null);}else{$0=$1.Parse(utcStr,inPattern,null);}var $2=Date.UTC($0.getFullYear(),$0.getMonth(),$0.getDate(),$0.getHours(),$0.getMinutes(),$0.getSeconds(),$0.getMilliseconds());var $3=$1.OffsetBetweenTimeZones($0,this.GetTimeZone(),null);var $4=new Date($2+$0.getTimezoneOffset()*60000+$3*60000);return $1.Format($4,'yyyy-MM-ddTHH:mm:ss',null);},ConvertNeutralToUtcDateTime:function(neutralStr,outPattern){if(neutralStr==null||!String.isNullOrEmpty(outPattern)&&outPattern.indexOf('z')>-1){return null;}var $0;var $1=CultureInfo.InvariantCulture.DateTimeFormat;$0=$1.Parse(neutralStr,null,null);var $2=Date.UTC($0.getFullYear(),$0.getMonth(),$0.getDate(),$0.getHours(),$0.getMinutes(),$0.getSeconds(),$0.getMilliseconds());var $3=$1.OffsetBetweenTimeZones($0,this.GetTimeZone(),null);var $4=new Date($2+$0.getTimezoneOffset()*60000-$3*60000);return $1.Format($4,outPattern,null);},GetLocale:function(){return this.$0;},GetLanguageCode:function(){return this.$1;},GetLanguageSuffix:function(){return this.$2;},GetDefaultLanguageCode:function(){return this.$3;},GetDefaultLanguageSuffix:function(){return this.$4;},GetTimeZone:function(){return this.$5;},GetCorporateToLocalOffset:function(){return this.$6;},GetUIDatePattern:function(innovatorDatePattern){return Aras.I18NUtils._I18NConverter.$B(innovatorDatePattern,this.GetLocale());}}
Aras.IOM.IOMScriptSharp$5=function(userName,passwordOrPasswordHash){this.$1=userName;this.$0=passwordOrPasswordHash;}
Aras.IOM.IOMScriptSharp$5.prototype={$0:null,$1:null,get_$2:function(){return this.$1;},get_$3:function(){return this.$0;}}
Aras.IOM.InternalUtils=function(){}
Aras.IOM.InternalUtils.createXmlDocument=function(){var $0=new XmlDocument();return $0;}
Aras.IOM.InternalUtils.createAndLoadXmlDocument=function(xmlValue){var $0=new XmlDocument();$0.loadXML(xmlValue);return $0;}
Aras.IOM.InternalUtils.loadXmlFromString=function(xmlDocument,xmlValue){xmlDocument.loadXML(xmlValue);}
Aras.IOM.InternalUtils.$0=function($p0,$p1){return (Type.safeCast($p0.getAttribute($p1),String))||'';}
Aras.IOM.InternalUtils.$1=function($p0){var $0=$p0.nodeType;return $0;}
Aras.IOM.InternalUtils.$2=function($p0,$p1){var $0=$p0.selectSingleNode('./@'+$p1)!=null;return $0;}
Aras.IOM.XmlExtension=function(){}
Aras.IOM.XmlExtension.getXml=function(node){return node.xml;}
Aras.IOM.IomFactory=function(){}
Aras.IOM.IomFactory.prototype={CreateInnovator:function(serverConnection){return new Aras.IOM.Innovator(serverConnection);},CreateArrayList:function(){return [];},CreateItemCache:function(){return new Aras.IOME.ItemCache();},CreateCacheableContainer:function(value,dependenciesSource){return new Aras.IOME.CacheableContainer(value,dependenciesSource);},CreateHttpServerConnection:function(innovatorServerUrl,database,userName,password,culture,timeZone){return new Aras.IOM.HttpServerConnection(innovatorServerUrl,database,userName,password,culture,timeZone);},CreateRestrictedHttpServerConnection:function(innovatorServerUrl){return new Aras.IOM.IOMScriptSharp$6(innovatorServerUrl);},CreateWinAuthHttpServerConnection:function(innovatorServerUrl,database){return new Aras.IOM.WinAuthHttpServerConnection(innovatorServerUrl,database);}}
Aras.IOM.HttpServerConnection=function(innovatorServerUrl,database,userName,password,culture,timeZone){Aras.IOM.HttpServerConnection.initializeBase(this);if(!Aras.IOM.HttpServerConnection.$19.test(password)){throw new Error('Not Implemented');}this.Compression='none';if(!String.isNullOrEmpty(culture)){this.set_locale(culture);}if(!String.isNullOrEmpty(timeZone)){this.set_timeZoneName(timeZone);}if(!innovatorServerUrl.endsWith('Server/InnovatorServer.aspx')){innovatorServerUrl+=((!innovatorServerUrl.endsWith('/'))?'/':'')+'Server/';}else if(innovatorServerUrl.endsWith('Server/InnovatorServer.aspx')){innovatorServerUrl=innovatorServerUrl.replace(new RegExp('InnovatorServer.aspx$',RegexOptions.ignoreCase),'');}this.$F=innovatorServerUrl;this.$E=String.format('{0}InnovatorServer.aspx',this.$F);this.$10=database;this.$1A=new Aras.IOM.IOMScriptSharp$5(userName,password);}
Aras.IOM.HttpServerConnection.$14=function($p0,$p1,$p2){if(String.isNullOrEmpty($p2)){return;}var $0=$p0.ownerDocument.createElement($p1);$0.text=$p2;$p0.appendChild($0);}
Aras.IOM.HttpServerConnection.$18=function($p0,$p1,$p2,$p3,$p4){Aras.IOM.InternalUtils.loadXmlFromString($p0,Aras.IOM.HttpServerConnection.$13);var $0=$p0.selectSingleNode('//faultstring');$0.text=$p2;if(!String.isNullOrEmpty($p1)){var $1=$p0.selectSingleNode('//faultcode');$1.text=$p1;}if(!String.isNullOrEmpty($p3)){var $2=$p0.selectSingleNode('//faultactor');$2.text=$p3;}if($p4!=null){var $3=$p0.selectSingleNode('//detail');$3.parentNode.replaceChild($p4,$3);}}
Aras.IOM.HttpServerConnection.prototype={$E:null,$F:null,$10:null,$11:null,$12:false,CallAction:function(actionName,inDom,outDom){this.callActionImpl(actionName,inDom,outDom,this.$E,true);},DebugLog:function(reason,msg){throw new Error('Not implemented');},DebugLogP:function(){throw new Error('Not implemented');},getUserID:function(){if(!this.$12){throw new Error('Not logged in');}if(this.cachedUserInfo!=null){return this.cachedUserInfo.getID();}var $0=Aras.IOM.InternalUtils.createAndLoadXmlDocument('<Empty />');var $1=Aras.IOM.InternalUtils.createAndLoadXmlDocument('<Empty />');this.CallAction('GetCurrentUserID',$0,$1);var $2=$1.selectSingleNode(Aras.IOM.Item.xPathResult);if($2!=null){return $2.text;}throw new Error('Cannot obtain user id');},GetDatabaseName:function(){return this.$10;},GetOperatingParameter:function(name,defaultvalue){return defaultvalue;},GetSrvContext:function(){return (null);},GetValidateUserXmlResult:function(){return this.$11;},GetLicenseInfo:function(issuer,addonName){var $0=Aras.IOM.InternalUtils.createXmlDocument();var $1=Aras.IOM.InternalUtils.createXmlDocument();Aras.IOM.InternalUtils.loadXmlFromString($0,'<Item/>');Aras.IOM.InternalUtils.loadXmlFromString($1,'<Empty/>');Aras.IOM.HttpServerConnection.$14($0.documentElement,'issuer',issuer);Aras.IOM.HttpServerConnection.$14($0.documentElement,'name',addonName);this.callActionImpl('GetLicenseInfo',$0,$1,this.$F+'License.aspx',true);return Aras.IOM.XmlExtension.getXml($1.documentElement);},$15:0,get_Timeout:function(){return this.$15;},set_Timeout:function(value){if((value<0)&&(value!==-1)){throw new Error("Timeout can be only be set to 'System.Threading.Timeout.Infinite' or a value >= 0.");}this.$15=value;return value;},$16:0,get_ReadWriteTimeout:function(){return this.$16;},set_ReadWriteTimeout:function(value){if((value<0)&&(value!==-1)){throw new Error("Timeout can be only be set to 'System.Threading.Timeout.Infinite' or a value >= 0.");}this.$16=value;return value;},Login:function(){var $0=Aras.IOM.InternalUtils.createXmlDocument();var $1=Aras.IOM.InternalUtils.createXmlDocument();Aras.IOM.InternalUtils.loadXmlFromString($0,'<Item/>');Aras.IOM.InternalUtils.loadXmlFromString($1,'<Empty/>');this.CallAction('ValidateUser',$0,$1);var $2=$1.selectSingleNode('//Result/id');if($2==null){var $4=null;var $5=$1.selectSingleNode(Aras.IOM.Item.xPathFault);var $6=new Aras.IOM.Innovator(this);var $7;if($5!=null){$7=$6.newItem();$7.dom=$1;}else{$4='Failed to login';$7=$6.newError($4);}return $7;}this.$12=true;var $3=this.getUserInfo();if($3.isError()){this.$12=false;}return $3;},Logout:function(unlockOnLogout){var $0=new XmlDocument();var $1=new XmlDocument();var $2=(unlockOnLogout)?0:1;Aras.IOM.InternalUtils.loadXmlFromString($0,"<logoff skip_unlock='"+$2+"'/>");Aras.IOM.InternalUtils.loadXmlFromString($1,'<Empty/>');this.CallAction('Logoff',$0,$1);this.$12=false;this.cachedUserInfo=null;},$17:null,usingParameters:function(parameters,action){this.$17=parameters;try{if(action!=null){action();}}finally{this.$17=null;}},$1A:null,get_userName:function(){return this.$1A.get_$2();},get_userPassword:function(){return this.$1A.get_$3();},callActionImpl:function(actionName,inDom,outDom,url,doSetHeaders){var $0=this.$1C(inDom,url,actionName,doSetHeaders);if($0.status===200){try{Aras.IOM.InternalUtils.loadXmlFromString(outDom,$0.responseText);}catch($1){Aras.IOM.HttpServerConnection.$18(outDom,null,Type.getInstanceType($1).get_fullName()+': '+$1.message,null,null);return;}}else{Aras.IOM.HttpServerConnection.$18(outDom,null,'no response from Innovator server '+this.$E,null,null);return;}if(actionName!=null&&'validateuser'===actionName.toLowerCase()){this.$11=$0.responseText;var $2=new Aras.IOM.I18NSessionContext(this.$11);this.set_locale($2.GetLocale());this.set_timeZoneName($2.GetTimeZone());}},$1B:function($p0,$p1,$p2,$p3){var $0=this.$1C($p0,$p1,$p2,$p3);return $0;},$1C:function($p0,$p1,$p2,$p3){if($p0==null||$p0.documentElement==null){throw new Error('inDom');}if(String.isNullOrEmpty($p1)){throw new Error('url');}var $0=TopWindowHelper.getMostTopWindowWithAras(window).aras.XmlHttpRequestManager.CreateRequest();$0.open('POST',$p1,false);var $1="<?xml version='1.0' encoding='utf-8' ?>";var $2=$1+$p0.documentElement.xml;$0.setRequestHeader('Content-Type','text/xml');if($p3){$0.setRequestHeader('SOAPAction',$p2);$0.setRequestHeader('AUTHUSER',this.get_userName());$0.setRequestHeader('AUTHPASSWORD',this.get_userPassword());$0.setRequestHeader('DATABASE',this.$10);$0.setRequestHeader('LOCALE',this.get_locale());$0.setRequestHeader('TIMEZONE_NAME',this.get_timeZoneName());}if(this.$17!=null&&this.$17.forceWritableSession){$0.setRequestHeader('Aras-Set-HttpSessionState-Behavior','required');}if($0.timeout>0||$0.timeout===-1){$0.timeout=this.get_Timeout();$0.send($2);}else{$0.send($2);}return $0;},getFileUrl:function(fileId,type){if(fileId==null){throw new Error('fileId');}var $0=Aras.IOM.HttpServerConnection.callBaseMethod(this, 'getFileUrl',[fileId,0]);return $0;},Compression:null,getFileUrls:function(fileIds,type){if(fileIds==null){throw new Error('fileIds');}if(!fileIds.length){throw new Error('List cannot be empty. Parameter name: fileIds');}var $0=Aras.IOM.HttpServerConnection.callBaseMethod(this, 'getFileUrls',[fileIds,0]);return [$0];},GetDatabases:function(){var $0=new ss.StringBuilder(this.$F);$0.append('DBList.aspx');var $1=$0.toString();var $2=TopWindowHelper.getMostTopWindowWithAras(window).aras.XmlHttpRequestManager.CreateRequest();$2.open('GET',$1,false);$2.send(null);var $3=new XmlDocument();Aras.IOM.InternalUtils.loadXmlFromString($3,$2.responseText);var $4=$3.selectNodes('DBList/DB/@id');var $5=new Array($4.length);for(var $6=0;$6<$4.length;$6++){$5[$6]=$4[$6].text;}return $5;}}
Aras.IOM.Innovator=function(serverConnection){this.$1={};if(serverConnection==null){throw new Error('serverConnection');}this.$0=serverConnection;}
Aras.IOM.Innovator.$3=function(){return TopWindowHelper.getMostTopWindowWithAras(window).aras.GUIDManager.GetGUID();;}
Aras.IOM.Innovator.scalcMD5=function(val){return calcMD5(val);}
Aras.IOM.Innovator.prototype={$0:null,applyAML:function(AML){var $0=this.newXMLDocument();var $1=this.newXMLDocument();Aras.IOM.InternalUtils.loadXmlFromString($0,AML);Aras.IOM.InternalUtils.loadXmlFromString($1,'<Empty />');this.$0.CallAction('ApplyAML',$0,$1);return this.$2($1);},applyMethod:function(methodName,body){var $0=this.newXMLDocument();var $1=this.newXMLDocument();Aras.IOM.InternalUtils.loadXmlFromString($0,"<Item type='Method'>"+body+'</Item>');$0.documentElement.setAttribute('action',methodName);Aras.IOM.InternalUtils.loadXmlFromString($1,'<Empty />');this.$0.CallAction('ApplyMethod',$0,$1);return this.$2($1);},$2:function($p0){var $0=Aras.IOM.Item.$0(this.$0,'','','simple');if($p0.selectSingleNode(Aras.IOM.Item.xPathFault)!=null){$0.dom=$p0;}else{$0.loadAML(Aras.IOM.XmlExtension.getXml($p0));}return $0;},newXMLDocument:function(){return Aras.IOM.InternalUtils.createXmlDocument();},getConnection:function(){return this.$0;},getI18NSessionContext:function(){var $0=this.$0.GetValidateUserXmlResult();if(String.isNullOrEmpty($0)){$0='';}if(Object.keyExists(this.$1,$0)){return this.$1[$0];}var $1;$1=new Aras.IOM.I18NSessionContext($0);this.$1[$0]=$1;return $1;},getNewID:function(){return Aras.IOM.Innovator.$3();},getNextSequence:function(sequenceName){var $0=this.newXMLDocument();Aras.IOM.InternalUtils.loadXmlFromString($0,'<Item><name/></Item>');var $1=$0.selectSingleNode('Item/name');if($1!=null){$1.text=sequenceName;}var $2=this.newXMLDocument();this.$0.CallAction('GetNextSequence',$0,$2);var $3=$2.selectSingleNode(Aras.IOM.Item.xPathResult);return ($3==null)?null:$3.text;},newItem:function(itemTypeName,action){if(ss.isNullOrUndefined(action)){if(ss.isNullOrUndefined(itemTypeName)){return Aras.IOM.Item.$0(this.$0,null,null,'full');}else{return Aras.IOM.Item.$0(this.$0,itemTypeName,null,'full');}}return Aras.IOM.Item.$0(this.$0,itemTypeName,action,'full');},getUserID:function(){return this.$0.getUserID();},getItemById:function(itemTypeName,id){if(itemTypeName==null||!itemTypeName.trim().length){throw new Error('Item type must be specified');}if(id==null||!id.trim().length){throw new Error('ID must be specified');}var $0=this.newXMLDocument();var $1=this.newXMLDocument();Aras.IOM.InternalUtils.loadXmlFromString($0,"<Item type='"+itemTypeName+"' id='"+id+"' />");Aras.IOM.InternalUtils.loadXmlFromString($1,'<Empty />');this.$0.CallAction('GetItem',$0,$1);var $2=this.$2($1);return ($2.isError()&&$2.getErrorCode()==='0')?null:$2;},getItemByKeyedName:function(itemTypeName,keyedName){if(itemTypeName==null||!itemTypeName.trim().length){throw new Error('Item type must be specified');}if(keyedName==null||!keyedName.trim().length){throw new Error('Keyed name must be specified');}var $0=this.newXMLDocument();var $1=this.newXMLDocument();Aras.IOM.InternalUtils.loadXmlFromString($0,"<Item type='"+itemTypeName+"'><keyed_name/></Item>");$0.documentElement.selectSingleNode('//keyed_name').text=keyedName;Aras.IOM.InternalUtils.loadXmlFromString($1,'<Empty />');this.$0.CallAction('GetItem',$0,$1);var $2=this.$2($1);return ($2.isError()&&$2.getErrorCode()==='0')?null:$2;},getUserAliases:function(){var $0=Aras.IOM.Item.$0(this.$0,'Alias',null,'full');$0.setProperty('source_id',this.getUserID(),null);var $1=$0.apply('get');var $2=$1.dom.selectNodes(Aras.IOM.Item.xPathResult+"/Item[@type='Alias']/related_id/Item[@type='Identity']");var $3=new Array($2.length);for(var $4=0;$4<$2.length;$4++){var $5=Aras.IOM.InternalUtils.$0($2[$4],'id');if(!$5){return '';}$3[$4]=$5;}return $3.join(',');},getFileUrl:function(fileId,type){return this.$0.getFileUrl(fileId,type);},getFileUrls:function(fileIds,type){return this.$0.getFileUrls(fileIds,type);},newError:function(explanation){var $0=Aras.IOM.Item.$0(this.$0,'','','full');var $1=Aras.SoapConstants._Soap.$6+'<'+'SOAP-ENV'+':Fault>\r\n\t\t\t<faultcode>1</faultcode>\r\n\t\t\t<faultactor></faultactor>\r\n\t\t\t</'+'SOAP-ENV'+':Fault>'+Aras.SoapConstants._Soap.$7;var $2=Aras.IOM.InternalUtils.createXmlDocument();Aras.IOM.InternalUtils.loadXmlFromString($2,$1);var $3=$2.selectSingleNode(Aras.SoapConstants._Soap.$F);var $4=$3.appendChild($2.createElement('faultstring'));$4.text=explanation;$0.dom=$2;return $0;},consumeLicense:function(featureName){var $0=new Aras.IOME.Licensing.LicenseManager(this.$0);return $0.consumeLicense(featureName);},newResult:function(resultBody){var $0=Aras.IOM.Item.$24(this.$0);Aras.IOM.InternalUtils.loadXmlFromString($0.dom,Aras.SoapConstants._Soap.$6+'<Result />'+Aras.SoapConstants._Soap.$7);$0.node=null;$0.nodeList=null;var $1=$0.dom.selectSingleNode('/'+Aras.SoapConstants._Soap.$D+'/Result');$1.text=resultBody;var $2=new XmlDocument();Aras.IOM.InternalUtils.loadXmlFromString($2,Aras.IOM.XmlExtension.getXml($0.dom));return $0;},applySQL:function(sql){var $0=this.newXMLDocument();var $1=this.newXMLDocument();Aras.IOM.InternalUtils.loadXmlFromString($0,'<sql />');$0.documentElement.text=sql;Aras.IOM.InternalUtils.loadXmlFromString($1,'<Empty />');this.$0.CallAction('ApplySQL',$0,$1);return this.$2($1);},getItemInDom:function(dom){if(dom==null){return null;}var $0=dom.selectSingleNode('//Item');if($0==null){return null;}var $1=Aras.IOM.Item.$24(this.$0);Aras.IOM.InternalUtils.loadXmlFromString($1.dom,Aras.IOM.XmlExtension.getXml(dom));$1.node=$1.dom.selectSingleNode('//Item');return $1;},calcMD5:function(val){throw new Error('Not Implemented');},getAssignedActivities:function(state,userId){throw new Error('Not Implemented');}}
Aras.IOM.Item=function(serverConnection,itemTypeName,action,mode){if(String.isNullOrEmpty(mode)||String.equals(mode,'simple',StringComparison.ordinalIgnoreCase)){this.dom=null;this.node=null;this.nodeList=null;this.serverConnection=serverConnection;}else{this.dom=this.newXMLDocument();this.node=this.dom.createElement('Item');this.dom.appendChild(this.node);this.node.setAttribute('isNew','1');this.node.setAttribute('isTemp','1');this.nodeList=null;this.serverConnection=serverConnection;if(itemTypeName!=null&&!!itemTypeName.trim().length){this.setType(itemTypeName);if(action!=null&&!!action.trim().length){this.setAction(action);if(String.equals(action,'add',StringComparison.ordinalIgnoreCase)||String.equals(action,'create',StringComparison.ordinalIgnoreCase)){this.setNewID();}}}}this.$27=new Aras.IOM.Innovator(serverConnection);}
Aras.IOM.Item.$0=function($p0,$p1,$p2,$p3){if(ss.isNullOrUndefined($p3)){if(ss.isNullOrUndefined($p2)){if(ss.isNullOrUndefined($p1)){return new Aras.IOM.Item($p0,'','','simple');}else{return new Aras.IOM.Item($p0,$p1,'','simple');}}else{return new Aras.IOM.Item($p0,$p1,$p2,'simple');}}return new Aras.IOM.Item($p0,$p1,$p2,$p3);}
Aras.IOM.Item.$1C=function($p0){var $0=$p0.getItemsByXPath("Relationships/Item[@type='Located']");if($0.getItemCount()===1){var $1='';$0=$0.getItemByIndex(0);var $2=$0.getPropertyItem('related_id');if($2!=null){$1=$2.getID();if(!$1.trim().length){if($2.getAction()==='get'){$2=$2.apply();if(!$2.isError()){$1=$2.getID();}}}}else{$1=$0.getProperty('related_id');}if(!$1.trim().length){var $3;$3=String.format("Vault ID is not specified in the following AML fragment: '{0}'",Aras.IOM.XmlExtension.getXml($p0.node));throw new Error($3);}return $1;}return null;}
Aras.IOM.Item.$22=function($p0,$p1){var $0='';var $1=0;while(Aras.IOM.InternalUtils.$1($p0)!==9){if($p1&&!$1){$0='';}else{$0=String.format('/*[position()={0}]{1}',Aras.IOM.Item.$23($p0),$0);}$1++;$p0=$p0.parentNode;}return $0;}
Aras.IOM.Item.$23=function($p0){var $0=0;var $1=$p0.parentNode.selectNodes('./*');var $enum1=ss.IEnumerator.getEnumerator($1);while($enum1.moveNext()){var $2=$enum1.current;if(Aras.IOM.InternalUtils.$1($2)!==1){continue;}$0++;if($2===$p0){break;}}return $0;}
Aras.IOM.Item.$24=function($p0){return Aras.IOM.Item.$0($p0,null,null,'full');}
Aras.IOM.Item.prototype={newItem:function(itemTypeName,action){if(ss.isNullOrUndefined(action)){if(ss.isNullOrUndefined(itemTypeName)){return Aras.IOM.Item.$0(this.serverConnection,null,null,'full');}else{return Aras.IOM.Item.$0(this.serverConnection,itemTypeName,null,'full');}}return Aras.IOM.Item.$0(this.serverConnection,itemTypeName,action,'full');},newInnovator:function(){return new Aras.IOM.Innovator(this.serverConnection);},serverConnection:null,dom:null,node:null,nodeList:null,loadAML:function(AML){if(this.dom==null){this.dom=new XmlDocument();}try{Aras.IOM.InternalUtils.loadXmlFromString(this.dom,AML);if(!!this.dom.parseError.errorCode){throw new Error('Data at the root level is invalid. '+this.dom.parseError.reason);}}catch($0){this.dom=null;throw $0;}finally{this.$11();}},clone:function(cloneRelationships){if(!this.$12(4)){throw new Error('Not a single item');}var $0=this.newItem(null,null);Aras.IOM.InternalUtils.loadXmlFromString($0.dom,Aras.IOM.XmlExtension.getXml(this.node));$0.node=$0.dom.selectSingleNode('//Item');$0.setNewID();$0.setAction('add');if(!cloneRelationships){var $1=$0.node.selectSingleNode('Relationships');if($1!=null){$1.parentNode.removeChild($1);}}else{var $2=$0.node.selectNodes('.//Relationships/Item');for(var $3=0;$3<$2.length;$3++){($2[$3]).setAttribute('id',this.getNewID());($2[$3]).setAttribute('action','add');}}return $0;},$11:function(){if(this.dom==null){this.node=null;this.nodeList=null;}else{var $0=this.dom.selectNodes('Item|AML/Item|//Result/Item');if(!$0.length){this.node=null;this.nodeList=null;}else if($0.length>1){this.node=null;this.nodeList=$0;}else{this.node=$0[0];this.nodeList=null;}}},$12:function($p0){if(this.dom==null){return false;}if(!!($p0&1)){if(this.node==null||!this.$13(this.node)){return false;}}if(!!($p0&2)){if(this.nodeList==null||!this.nodeList.length){return false;}else{var $enum1=ss.IEnumerator.getEnumerator(this.nodeList);while($enum1.moveNext()){var $0=$enum1.current;if(!this.$13($0)){return false;}}}}if(!!($p0&4)){if(this.node==null||this.node.nodeName!=='Item'){return false;}}if(!!($p0&8)){if(this.nodeList==null||!this.nodeList.length){return false;}else{var $enum2=ss.IEnumerator.getEnumerator(this.nodeList);while($enum2.moveNext()){var $1=$enum2.current;var $2=$1.nodeName;if(!String.equals($2,'Item',StringComparison.ordinalIgnoreCase)){return false;}}}}if(!!($p0&16)){if(this.nodeList==null||!this.nodeList.length){return false;}else if(this.nodeList.length>1){var $3=this.nodeList[0].parentNode;for(var $4=1;$4<this.nodeList.length;$4++){if(this.nodeList[$4].parentNode!==$3){return false;}}}}if(!!($p0&32)){if(this.node==null){return false;}else{var $5=this.node.nodeName;if(!String.equals($5,'and',StringComparison.ordinalIgnoreCase)&&!String.equals($5,'or',StringComparison.ordinalIgnoreCase)&&!String.equals($5,'not',StringComparison.ordinalIgnoreCase)){return false;}}}return true;},newXMLDocument:function(){var $0=new XmlDocument();return $0;},$13:function($p0){if($p0.ownerDocument!==this.dom){return false;}var $0=false;while($p0.parentNode!=null){var $1=$p0.parentNode;if(Aras.IOM.InternalUtils.$1($1)===9){$0=true;break;}$p0=$1;}return $0;},apply:function(arg,argsObject){var $0=Type.safeCast(arg,String);if($0==null&&arg!=null){argsObject=Type.safeCast(arg,Object);}this.$14($0,argsObject);var $1=Type.safeCast(this.serverConnection,Aras.IOM.ServerConnectionBase);if(null!==$1&&$1.get_$3()&&this.$1B()){return this.$15($1);}var $2=this.newXMLDocument();var $3=this.newXMLDocument();Aras.IOM.InternalUtils.loadXmlFromString($3,Aras.IOM.XmlExtension.getXml(this.node));this.serverConnection.CallAction('ApplyItem',$3,$2);var $4=Aras.IOM.Item.$0(this.serverConnection,null,null,null);$4.dom=$2;if($2.selectSingleNode(Aras.IOM.Item.xPathFault+'/faultcode')==null){$4.$11();}return $4;},$14:function($p0,$p1){if(!this.$12(4)){if(this.dom.selectSingleNode('a/WorkflowMap')==null){throw new Error('Not a single item');}}if(!this.$12(1)){throw new Error(String.format(Aras.IOM.Item.$6,"'this' item"));}if(!String.isNullOrEmpty($p0)){this.node.setAttribute('action',$p0);}if(($p1!=null)&&(Object.getKeyCount($p1)>0)){var $enum1=ss.IEnumerator.getEnumerator(Object.keys($p1));while($enum1.moveNext()){var $0=$enum1.current;this.setProperty($0,$p1[$0].toString(),null);}}},$15:function($p0,$p1){var $0=this.$1A();var $1=this.$17($0);var $2=this.$19();var $3='';if(this.node!=null){$3=Aras.IOM.XmlExtension.getXml(this.node);}else{for(var $6=0;$6<this.nodeList.length;$6++){$3+=Aras.IOM.XmlExtension.getXml(this.nodeList[$6]);}}var $4=$p0.$D('ApplyAML',$2,$3,$1,$0,$p1);var $5=this.newItem();$5.loadAML($4);return $5;},$16:function(){var $0=this.serverConnection;return $0.getUserInfo();},$17:function($p0){var $0=null;if(!String.isNullOrEmpty($p0)){var $1=this.$2E();if(String.equals($1,$p0,StringComparison.ordinalIgnoreCase)){var $2=this.$16();$0=$2.getPropertyItem('default_vault').getProperty('vault_url');}else{var $3=this.newItem();$3.loadAML("<Item type='Vault' id='"+$p0+"' action='get' select='vault_url' />");var $4=$3.apply();if($4.isError()){throw new Error($4.getErrorString());}$0=$4.getProperty('vault_url');}if(String.isNullOrEmpty($0)){throw new Error("Failed to obtain vault URL for vault with ID='"+$p0+"'");}}return $0;},$18:function(){return this.getItemsByXPath('descendant-or-self::Item['+"@type='File' and "+"(@action='add' or @action='create') and "+"actual_filename and Relationships/Item[@type='Located']/related_id]");},$19:function(){var $0=this.$18();var $1={};for(var $2=0;$2<$0.getItemCount();$2++){var $3=$0.getItemByIndex($2);var $4=$3.getItemsByXPath("Relationships/Item[@type='Located']");if($4.getItemCount()>1){var $6;$6=String.format("Ambigious vaults are specified on the file: '{0}'",Aras.IOM.XmlExtension.getXml($3.node));throw new Error($6);}var $5=$3.getProperty('actual_filename');if(!String.isNullOrEmpty($5)){var $7=$5;var $8=new EasyFileInfo(TopWindowHelper.getMostTopWindowWithAras(window).aras.vault);$3.setProperty('checksum',$8.getFileChecksum($3.getID()));$3.setProperty('file_size',$8.getFileSize($3.getID()).toString());var $9=$3.getID();if(String.isNullOrEmpty($9)){var $A=$3.getAttribute('action','').trim();var $B;if(!String.equals($A,'add',StringComparison.ordinalIgnoreCase)&&!String.equals($A,'create',StringComparison.ordinalIgnoreCase)){$B=String.format("File ID is not set in the following AML fragment: '{0}'",Aras.IOM.XmlExtension.getXml($3.node));throw new Error($B);}$9=$3.getNewID();$3.setID($9);}$1[$9]=$7;}}return $1;},$1A:function(){var $0=this.$18();var $1=null;for(var $2=0;$2<$0.getItemCount();$2++){var $3=$0.getItemByIndex($2);var $4=Aras.IOM.Item.$1C($3);if($1==null){$1=$4;}else if($1!==$4){throw new Error("Only one Vault Server may be specified in 'Located' for all Files are submitted in the same transaction.");}}return $1;},$1B:function(){var $0=this.node.selectSingleNode('descendant-or-self::Item['+"@type='File' and "+"(@action='add' or @action='create') and "+"actual_filename and Relationships/Item[@type='Located']/related_id]");return ($0!=null);},getAttribute:function(attributeName,defaultValue){if(!this.$12(4)){throw new Error('Not a single item');}if(Aras.IOM.InternalUtils.$2(this.node,attributeName)){return Aras.IOM.InternalUtils.$0(this.node,attributeName);}else{return defaultValue;}},setAttribute:function(attributeName,attributeValue){if(!this.$12(4)){throw new Error('Not a single item');}this.node.setAttribute(attributeName,attributeValue);},removeAttribute:function(attributeName){if(!this.$12(4)){throw new Error('Not a single item');}if(Aras.IOM.InternalUtils.$2(this.node,attributeName)){this.node.removeAttribute(attributeName);}},getAction:function(){if(!this.$12(4)){throw new Error('Not a single item');}return this.getAttribute('action','');},setAction:function(action){if(!this.$12(4)){throw new Error('Not a single item');}this.setAttribute('action',action);},getInnovator:function(){return this.$27;},getID:function(){if(!this.$12(4)){throw new Error('Not a single item');}var $0=this.getAttribute('id','');if(String.isNullOrEmpty($0)){var $1=this.node.selectSingleNode('id');if($1!=null){var $2=null;if(Aras.IOM.InternalUtils.$2($1,'condition')){$2=Aras.IOM.InternalUtils.$0($1,'condition');}if(String.isNullOrEmpty($2)||String.equals($2,'eq',StringComparison.ordinalIgnoreCase)){$0=$1.text.trim();}}}return $0;},setID:function(id){if(!this.$12(4)){throw new Error('Not a single item');}this.setAttribute('id',id);var $0=this.node.selectSingleNode('id');if($0!=null){$0.text=id;}},getType:function(){if(!this.$12(4)){throw new Error('Not a single item');}return this.getAttribute('type','');},setType:function(itemTypeName){if(!this.$12(4)){throw new Error('Not a single item');}this.setAttribute('type',itemTypeName);},getProperty:function(propertyName,defaultValue,lang){if(!this.$12(4)&&!this.$12(32)){throw new Error('Not a single item');}var $0=null;var $1=this.$2A(propertyName,lang);if($1!=null){var $2=$1.selectSingleNode('Item');if($2!=null){var $3=Aras.IOM.Item.$0(this.serverConnection,null,null,null);$3.dom=this.dom;$3.node=$2;$0=$3.getID();if(String.isNullOrEmpty($0)){$0=defaultValue;}}else{$0=$1.text;if(Aras.IOM.InternalUtils.$2($1,'is_null')&&String.isNullOrEmpty($0)&&String.equals(Aras.IOM.InternalUtils.$0($1,'is_null'),'1',StringComparison.ordinalIgnoreCase)){$0=defaultValue;}}}else{$0=defaultValue;}return $0;},setProperty:function(propertyName,propertyValue,lang){if(ss.isNullOrUndefined(lang)){lang=null;}if(!this.$12(4)&&!this.$12(32)){throw new Error('Not a single item');}var $0=this.$2A(propertyName,lang);if($0==null||String.equals(this.node.nodeName,'or',StringComparison.ordinalIgnoreCase)){$0=this.$29(propertyName,lang);}if(lang!=null){$0.setAttribute('xml:lang',lang);}if(propertyValue==null){$0.setAttribute('is_null','1');$0.text='';}else{if(Aras.IOM.InternalUtils.$2($0,'is_null')&&String.equals(Aras.IOM.InternalUtils.$0($0,'is_null'),'1',StringComparison.ordinalIgnoreCase)){$0.removeAttribute('is_null');}$0.text=propertyValue;}},removeProperty:function(propertyName,lang){if(!this.$12(4)&&!this.$12(32)){throw new Error('Not a single item');}var $0=this.$2A(propertyName,lang);if($0!=null){this.node.removeChild($0);}},getPropertyCondition:function(propertyName,lang){if(!this.$12(4)&&!this.$12(32)){throw new Error('Not a single item');}return this.getPropertyAttribute(propertyName,'condition',lang,null);},setPropertyCondition:function(propertyName,condition,lang){this.setPropertyAttribute(propertyName,'condition',condition,lang);},getPropertyAttribute:function(propertyName,attributeName,defaultValue,lang){if(!this.$12(4)&&!this.$12(32)){throw new Error('Not a single item');}var $0=this.$2A(propertyName,lang);if($0==null){return defaultValue;}if(Aras.IOM.InternalUtils.$2($0,attributeName)){return Aras.IOM.InternalUtils.$0($0,attributeName);}else{return defaultValue;}},setPropertyAttribute:function(propertyName,attributeName,attributeValue,lang){if(!this.$12(4)&&!this.$12(32)){throw new Error('Not a single item');}var $0=this.$2A(propertyName,lang);if($0==null){$0=this.$29(propertyName,lang);}$0.setAttribute(attributeName,attributeValue);if(lang!=null){$0.setAttribute('xml:lang',lang);}},removePropertyAttribute:function(propertyName,attributeName,lang){if(!this.$12(4)&&!this.$12(32)){throw new Error('Not a single item');}var $0=this.$2A(propertyName,lang);if($0!=null){$0.removeAttribute(attributeName);}},getPropertyItem:function(propertyName){if(!this.$12(4)&&!this.$12(32)){throw new Error('Not a single item');}if(propertyName==null){throw new Error('propertyName');}if(String.equals(propertyName,'id',StringComparison.ordinalIgnoreCase)){return this;}else{var $0=this.node.selectSingleNode(propertyName);if($0!=null){var $1=$0.selectSingleNode('Item');if($1!=null){var $2=Aras.IOM.Item.$0(this.serverConnection,null,null,null);$2.dom=this.dom;$2.node=$1;return $2;}else{var $3=Aras.IOM.InternalUtils.$0($0,'type');if(!$3.length){return null;}var $4=Aras.IOM.Item.$0(this.serverConnection,null,null,null);$4.dom=new XmlDocument();Aras.IOM.InternalUtils.loadXmlFromString($4.dom,String.format("<Item type='{0}' id='{1}'><id>{1}</id></Item>",$3,$0.text));$4.node=$4.dom.selectSingleNode('Item');return $4;}}return null;}},setPropertyItem:function(propertyName,item){this.$28(propertyName,item,true);return item;},setFileProperty:function(propertyName,pathToFile){if(String.isNullOrEmpty(propertyName)){throw new Error('propertyName');}var fileItem = this.newItem('File', 'add');fileItem.attachPhysicalFile(pathToFile);fileItem.setProperty("filename", pathToFile.name, null);this.setPropertyItem(propertyName, fileItem);return fileItem;return null;},fetchFileProperty:function(propertyName,targetPath,mode){if(String.isNullOrEmpty(propertyName)){throw new Error('propertyName');}if(String.isNullOrEmpty(targetPath)){throw new Error('targetPath');}var $0=this.getPropertyItem(propertyName);if($0!=null){switch(mode){case 0:$0=$0.$26(targetPath,null,1);break;case 1:$0.$25(targetPath,1);break;default:throw new Error('Agrument "mode" is not a part of FetchFileMode enumeration.');}}return $0;},fetchDefaultPropertyValues:function(overwrite_current){if(!this.$12(4)){throw new Error('Not a single item');}var $0=this.$32();var $1=Aras.IOM.Item.$0(this.serverConnection,null,null,'full');var $2="<Item type='ItemType' action='get' select='id'>"+' <name>'+$0+'</name>'+' <Relationships>'+"  <Item type='Property' action='get' select='name,default_value' />"+' </Relationships>'+'</Item>';$1.loadAML($2);var $3=$1.apply(null,null);if($3.isError()){return $3;}var $4=$3.dom.selectNodes("//Item[@type='ItemType']/Relationships/Item[@type='Property']");var $enum1=ss.IEnumerator.getEnumerator($4);while($enum1.moveNext()){var $5=$enum1.current;var $6=$5.selectSingleNode('name').text;var $7=$5.selectSingleNode('default_value');var $8=($7==null)?'':$7.text;if($8.length>0&&(overwrite_current||(!overwrite_current&&this.getProperty($6,null,null)==null))){this.setProperty($6,$8,null);}}return this;},getErrorDetail:function(){return this.$1D('detail');},setErrorDetail:function(detail){this.$1E('detail',detail);},getErrorString:function(){return this.$1D('faultstring');},setErrorString:function(errorMessage){this.$1E('faultstring',errorMessage);},getErrorWho:function(){return this.getErrorCode();},getErrorCode:function(){return this.$1D('faultcode');},getFileName:function(){this.$30();return this.getProperty('filename','',null);},setErrorWho:function(who){this.setErrorCode(who);},setErrorCode:function(errcode){this.$1E('faultcode',errcode);},setFileName:function(filePath){this.attachPhysicalFile(filePath);this.setProperty("filename", filePath.name, null);},getErrorSource:function(){return this.$1D('faultactor');},setErrorSource:function(source){this.$1E('faultactor',source);},$1D:function($p0){var $0='';if(this.dom!=null){var $1=this.dom.selectSingleNode(Aras.IOM.Item.xPathFault+'/'+$p0);if($1!=null){$0=$1.text;}}return $0;},$1E:function($p0,$p1){if(this.dom==null){return;}var $0=this.dom.selectSingleNode(Aras.IOM.Item.xPathFault);if($0!=null){var $1=$0.selectSingleNode($p0);if($1==null){$1=$0.appendChild(this.dom.createElement($p0));}$1.text=$p1;}},getResult:function(){var $0='';if(this.dom!=null){var $1=this.dom.selectSingleNode(Aras.IOM.Item.xPathResult);if($1!=null){$0=$1.text;}}return $0;},email:function(emailItem,identityItem){if(emailItem==null){throw new Error('emailItem');}if(identityItem==null){throw new Error('identityItem');}if(!this.$12(4)){throw new Error('Not a single item');}var $0=this.newXMLDocument();var $1=this.newXMLDocument();Aras.IOM.InternalUtils.loadXmlFromString($0,Aras.IOM.XmlExtension.getXml(this.node));Aras.IOM.InternalUtils.loadXmlFromString($1,'<Empty />');var $2=$0.selectSingleNode('//Item');$2.setAttribute('action','EmailItem');var $3=$2.appendChild($0.createElement('___aras_email_identity_name___'));$3.text=identityItem.getProperty('name');var $4=$2.appendChild($0.createElement('___aras_email_item___'));$4.appendChild(emailItem.node.cloneNode(true));this.serverConnection.CallAction('ApplyItem',$0,$1);if($1.selectSingleNode(Aras.IOM.Item.xPathFault+'/faultcode')!=null){return false;}else{return true;}},isNew:function(){if(!this.$12(4)){return false;}return String.equals(this.getAttribute('isNew',''),'1',StringComparison.ordinalIgnoreCase);},isRoot:function(){if(!this.$12(4)){return false;}var $0=this.node.selectNodes("ancestor::node()[local-name()='Item']");if($0.length>0){return false;}var $1=this.node.parentNode.selectNodes('Item');if($1.length>1){return false;}return true;},isCollection:function(){if(this.isError()){return false;}return (this.nodeList!=null&&this.node==null);},isLocked:function(){if(!this.$12(4)){throw new Error('Not a single item');}if(this.isNew()){return 0;}var $0='';if(!this.$2B('locked_by_id')){var $1=this.newItem(this.getType(),'get');$1.setAttribute('select','locked_by_id');$1.setID(this.getID());$1=$1.apply(null,null);if($1.isError()){throw new Error('Server returns fault in internal query');}if(!$1.$12(4)){throw new Error('Not a single item');}$0=$1.getProperty('locked_by_id','',null);}else{$0=this.getProperty('locked_by_id','',null);}if(String.isNullOrEmpty($0)){return 0;}else if(String.equals($0,this.serverConnection.getUserID(),StringComparison.ordinalIgnoreCase)){return 1;}else{return 2;}},fetchLockStatus:function(){var $0=this.$31();var $1=this.$32();var $2=this.newItem($1,'get');$2.setAttribute('select','locked_by_id');$2.setID($0);var $3=$2.apply();if($3.isError()){return -1;}var $4=$3.getProperty('locked_by_id','');this.setProperty('locked_by_id',$4);if(String.isNullOrEmpty($4)){return 0;}else if($4===this.serverConnection.getUserID()){return 1;}else{return 2;}},getLockStatus:function(){if(!this.$12(4)){throw new Error('Not a single item');}if(this.isNew()){return 0;}var $0=this.getProperty('locked_by_id','',null);if(!$0.length){return 0;}else if($0===this.serverConnection.getUserID()){return 1;}else{return 2;}},isError:function(){return (this.dom!=null&&this.dom.selectSingleNode(Aras.IOM.Item.xPathFault)!=null);},isEmpty:function(){if(this.isError()){return String.equals(this.getErrorCode(),'0',StringComparison.ordinalIgnoreCase);}else{return false;}},appendItem:function(item){if(item==null){throw new Error(String.format(Aras.IOM.Item.$6,"'this' item"));}var $0;if(this.node!=null){if(!this.$12(4|1)){throw new Error(String.format(Aras.IOM.Item.$6,"'this' item"));}if(item.node!=null){if(!item.$12(4)){throw new Error('The argument passed to the method is not a single item');}$0=this.$1F();$0.add(this.$21(item.node));}else if(item.nodeList!=null){if(!item.$12(8)){throw new Error("Not all elements of the passed item's nodeList are &lt;Item&gt; nodes");}$0=this.$1F();var $enum1=ss.IEnumerator.getEnumerator(item.nodeList);while($enum1.moveNext()){var $2=$enum1.current;$0.add(this.$21($2));}}else{throw new Error(String.format(Aras.IOM.Item.$6,'passed item'));}}else if(this.nodeList!=null){if(!this.$12(8|2)){throw new Error(String.format(Aras.IOM.Item.$6,"'this' item"));}if(!this.$12(16)){throw new Error("Not all nodes of 'this.nodeList' are siblings");}$0=[];this.$20($0);if(item.node!=null){if(!item.$12(4)){throw new Error('The argument passed to the method is not a single item');}$0.add(this.$21(item.node));}else if(item.nodeList!=null){if(!item.$12(8)){throw new Error("Not all elements of the passed item's nodeList are &lt;Item&gt; nodes");}var $enum2=ss.IEnumerator.getEnumerator(item.nodeList);while($enum2.moveNext()){var $3=$enum2.current;$0.add(this.$21($3));}}else{throw new Error(String.format(Aras.IOM.Item.$6,'passed item'));}}else{throw new Error(String.format(Aras.IOM.Item.$6,"'this' item"));}var $1='';var $enum3=ss.IEnumerator.getEnumerator($0);while($enum3.moveNext()){var $4=$enum3.current;if(String.isNullOrEmpty($1)){$1=Aras.IOM.Item.$22($4,true);$1=String.format('{0}/*[position()={1}',$1,Aras.IOM.Item.$23($4));}else{$1=String.format('{0} or position()={1}',$1,Aras.IOM.Item.$23($4));}}$1+=']';this.nodeList=this.dom.selectNodes($1);},removeItem:function(item){if(!this.$12(2|8)){throw new Error('Not a collection of items');}if(item==null){throw new Error('item');}if(this.dom!==item.dom){throw new Error(String.format("{0} and {1} must reference the same ArasXmlDocument through their 'dom' property","'this' item",'item passed to the method'));}var $0=[];if(item.$12(4)){var $2=item.node.selectNodes('descendant-or-self::Item');var $enum1=ss.IEnumerator.getEnumerator($2);while($enum1.moveNext()){var $3=$enum1.current;$0.add($3);}}else if(item.$12(8)){var $enum2=ss.IEnumerator.getEnumerator(item.nodeList);while($enum2.moveNext()){var $4=$enum2.current;var $5=$4.selectNodes('descendant-or-self::Item');var $enum3=ss.IEnumerator.getEnumerator($5);while($enum3.moveNext()){var $6=$enum3.current;if(!$0.contains($6)){$0.add($6);}}}}else{throw new Error(String.format(Aras.IOM.Item.$6,'item passed to the method'));}for(var $7=0;$7<$0.length;$7++){var $8=$0[$7];if(this.node!=null&&$8===this.node){this.node=null;break;}}var $1='';var $enum4=ss.IEnumerator.getEnumerator(this.nodeList);while($enum4.moveNext()){var $9=$enum4.current;if(!$0.contains($9)){if(String.isNullOrEmpty($1)){$1=Aras.IOM.Item.$22($9,true);$1=String.format('{0}/*[position()={1}',$1,Aras.IOM.Item.$23($9));}else{$1=String.format('{0} or position()={1}',$1,Aras.IOM.Item.$23($9));}}}$1+=']';if($1.length>0){var $A=this.dom.selectNodes($1);if($A.length===1){this.node=$A[0];this.nodeList=null;}else{this.nodeList=$A;var $B=this.nodeList.length;}}else{this.nodeList=null;}for(var $C=0;$C<$0.length;$C++){var $D=$0[$C];$D.parentNode.removeChild($D);}},getItemsByXPath:function(xpath){if(this.dom==null){throw new Error(String.format(Aras.IOM.Item.$6,"'this' item"));}var $0;if(this.node!=null){$0=this.node.selectNodes(xpath);}else{$0=this.dom.selectNodes(xpath);}var $1=Aras.IOM.Item.$0(this.serverConnection,null,null,null);$1.dom=this.dom;var $2=true;if($0.length===1){$1.node=$0[0];if(!$1.$12(4)){$2=false;}}else{$1.nodeList=$0;if($1.nodeList.length>0&&!$1.$12(8)){$2=false;}}if(!$2){throw new Error(String.format("Specified XPath '{0}' doesn't resolve to &lt;Item&gt; nodes",xpath));}return $1;},getItemCount:function(){if(this.dom==null){return -1;}if(this.nodeList!=null){return this.nodeList.length;}if(this.isError()){if(this.getErrorCode()==='0'){return 0;}else{return -1;}}else if(this.node==null){return -1;}else{return 1;}},getItemByIndex:function(index){if(this.nodeList==null){if(!!index){throw new Error('Item is not a collection');}else{return this;}}else{if(index>this.nodeList.length-1||index<0){throw new Error('IndexOutOfRangeException');}var $0=Aras.IOM.Item.$0(this.serverConnection,null,null,null);$0.dom=this.dom;$0.node=this.nodeList[index];return $0;}},lockItem:function(){var $0=this.$31();var $1=this.$32();var $2=this.newItem($1,'lock');$2.setID($0);var $3=$2.apply();if(!$3.isError()){this.setProperty('locked_by_id',$3.getProperty('locked_by_id',''));}return $3;},unlockItem:function(){var $0=this.$31();var $1=this.$32();var $2=this.newItem($1,'unlock');$2.setID($0);var $3=$2.apply();if(!$3.isError()){this.removeProperty('locked_by_id');}return $3;},fetchRelationships:function(relationshipTypeName,selectList,orderBy){if(!this.$12(4)){throw new Error('Not a single item');}var $0=this.getID();if(String.isNullOrEmpty($0)){throw new Error('ID is not set');}if(relationshipTypeName==null||!relationshipTypeName.trim().length){throw new Error('Relationship type is not specified');}var $1="<Item type='"+relationshipTypeName+"' action='get'><source_id>"+$0+'</source_id></Item>';var $2=this.newItem(null,null);$2.loadAML($1);if(selectList!=null&&selectList.trim().length>0){$2.setAttribute('select',selectList);}if(orderBy!=null&&orderBy.trim().length>0){$2.setAttribute('order_by',orderBy);}var $3=$2.apply();if($3.isError()){if($3.getErrorCode()!=='0'){return $3;}}else{var $4=this.node.selectNodes("Relationships/Item[@type='"+relationshipTypeName+"']");if($4!=null){var $enum1=ss.IEnumerator.getEnumerator($4);while($enum1.moveNext()){var $5=$enum1.current;if(this.nodeList==null){$5.parentNode.removeChild($5);}else{var $6=Aras.IOM.Item.$0(this.serverConnection,null,null,null);$6.dom=this.dom;$6.node=$5;this.removeItem($6);}}}if(!$3.isCollection()){this.addRelationship($3);}else{for(var $7=0;$7<$3.getItemCount();$7++){this.addRelationship($3.getItemByIndex($7));}}}return this;},getRelatedItem:function(){if(!this.$12(4)){throw new Error('Not a single item');}var $0=this.node.selectSingleNode('related_id');if($0!=null){var $1=$0.selectSingleNode('Item');if($1!=null){var $2=Aras.IOM.Item.$0(this.serverConnection,null,null,null);$2.dom=this.dom;$2.node=$1;return $2;}else{var $3=Aras.IOM.InternalUtils.$0($0,'type');if(!$3.length){return null;}var $4=Aras.IOM.Item.$0(this.serverConnection,null,null,null);$4.dom=new XmlDocument();Aras.IOM.InternalUtils.loadXmlFromString($4.dom,String.format("<Item type='{0}' id='{1}'><id>{1}</id></Item>",$3,$0.text));$4.node=$4.dom.selectSingleNode('Item');return $4;}}else{return null;}},setRelatedItem:function(ritem){this.$28('related_id',ritem,false);},addRelationship:function(item){if(!this.$12(4)){throw new Error('Not a single item');}if(item==null){throw new Error(String.format(Aras.IOM.Item.$6,"'this' item"));}if(!item.$12(4)){throw new Error('The argument passed to the method is not a single item');}var $0=this.node.selectSingleNode('Relationships');if($0==null){$0=this.node.appendChild(this.dom.createElement('Relationships'));}item.node=$0.appendChild(item.node.cloneNode(true));item.dom=this.dom;},getRelationships:function(itemTypeName){if(!this.$12(4)){throw new Error('Not a single item');}var $0=null;if(itemTypeName==null){$0=this.node.selectNodes('Relationships/Item');}else{$0=this.node.selectNodes("Relationships/Item[@type='"+itemTypeName+"']");}var $1=Aras.IOM.Item.$0(this.serverConnection,null,null,null);$1.dom=this.dom;$1.node=null;$1.nodeList=$0;return $1;},removeRelationship:function(item){if(!this.$12(4)){throw new Error('Not a single item');}if(item==null){throw new Error('item');}if(!item.$12(4)){throw new Error('The argument passed to the method is not a single item');}if(this.dom!==item.dom){throw new Error(String.format("{0} and {1} must reference the same ArasXmlDocument through their 'dom' property","'this' item",'item passed to the method'));}var $0=item.node.parentNode;if(String.equals($0.nodeName,'Relationships',StringComparison.ordinalIgnoreCase)){if(this.nodeList==null){$0.removeChild(item.node);}else{this.removeItem(item);}}else{throw new Error('The item pased to the method is not a relationship item.');}},getRelatedItemID:function(){var $0='';if(!this.$12(4)){throw new Error('Not a single item');}var $1=this.node.selectSingleNode('related_id');if($1!=null){var $2=$1.selectSingleNode('Item');if($2!=null){$0=Aras.IOM.InternalUtils.$0($2,'id');if(String.isNullOrEmpty($0)){$2=$2.selectSingleNode('id');if($2!=null){$0=$2.text;}}return $0;}else{$0=$1.text;}}return $0;},getParentItem:function(){if(!this.$12(4)){throw new Error('Not a single item');}var $0=this.node.selectSingleNode('ancestor::Item');if($0==null){return null;}var $1=Aras.IOM.Item.$0(this.serverConnection,null,null,null);$1.dom=this.dom;$1.node=$0;return $1;},isLogical:function(){return this.$12(32);},newAND:function(){if(!this.$12(4)&&!this.$12(32)){throw new Error('Not a single item');}var $0=Aras.IOM.Item.$0(this.serverConnection,null,null,null);$0.dom=this.dom;$0.node=this.node.appendChild(this.dom.createElement('and'));return $0;},newOR:function(){if(!this.$12(4)&&!this.$12(32)){throw new Error('Not a single item');}var $0=Aras.IOM.Item.$0(this.serverConnection,null,null,null);$0.dom=this.dom;$0.node=this.node.appendChild(this.dom.createElement('or'));return $0;},newNOT:function(){if(!this.$12(4)&&!this.$12(32)){throw new Error('Not a single item');}var $0=Aras.IOM.Item.$0(this.serverConnection,null,null,null);$0.dom=this.dom;$0.node=this.node.appendChild(this.dom.createElement('not'));return $0;},removeLogical:function(logicalItem){if(!this.$12(4)&&!this.$12(32)){throw new Error('Not a single item');}if(logicalItem==null){throw new Error('logicalItem');}if(!logicalItem.$12(32)){throw new Error('Passed item is not a logical item');}this.node.removeChild(logicalItem.node);},promote:function(state,comments){if(!this.$12(4)){throw new Error('Not a single item');}if(state==null||!state.trim().length){throw new Error("'state' is either 'null' or an empty string");}var $0=this.newItem(null,null);$0.loadAML(Aras.IOM.XmlExtension.getXml(this.node));$0.setProperty('state',state,null);if(comments!=null&&comments.trim().length>0){$0.setProperty('comments',comments,null);}return $0.apply('promoteItem');},$1F:function(){var $0=[];var $1=this.node.parentNode;if(Aras.IOM.InternalUtils.$1($1)===9){if(this.nodeList!=null&&(this.nodeList.length>1||this.nodeList.length===1&&this.nodeList[0]!==this.node)){throw new Error("'this.node' is not sibling to items in 'this.nodeList'");}Aras.IOM.InternalUtils.loadXmlFromString(this.dom,String.format('<AML>{0}</AML>',Aras.IOM.XmlExtension.getXml(this.dom)));this.nodeList=this.dom.selectNodes('/AML/Item');this.node=null;this.$20($0);}else{if(this.nodeList!=null){var $enum1=ss.IEnumerator.getEnumerator(this.nodeList);while($enum1.moveNext()){var $2=$enum1.current;if($2.nodeName!=='Item'){throw new Error(String.format("The following element of 'this.nodeList' is not an 'Item': {0}",Aras.IOM.XmlExtension.getXml($2)));}if($2.parentNode!==$1){throw new Error("'this.node' is not sibling to items in 'this.nodeList'");}}this.$20($0);this.node=null;}else{var $3=Aras.IOM.Item.$22(this.node,false);this.nodeList=this.dom.selectNodes($3);this.node=null;this.$20($0);}}return $0;},$20:function($p0){if(this.node!=null){$p0.add(this.node);}if(this.nodeList!=null){var $enum1=ss.IEnumerator.getEnumerator(this.nodeList);while($enum1.moveNext()){var $0=$enum1.current;$p0.add($0);}}},$21:function($p0){var $0=this.nodeList[0].parentNode;return $0.appendChild($p0.cloneNode(true));},checkout:function(dir){return this.$26(dir,null,0);},$25:function($p0,$p1){if(!this.$12(4)){throw new Error('Not a single item');}this.$30();this.$31();if(this.isNew()){throw new Error("The file was never stored on server ('isNew=1')");}var $0=this.getProperty('filename');if(String.isNullOrEmpty($0)){var $2=this.newItem('File','get');$2.setID(this.getID());$2.setAttribute('select','filename');var $3=$2.apply();if($3.isError()){throw new Error($3.getErrorString());}$0=$3.getProperty('filename');this.setProperty('filename',$0,null);}var $1=(!$p1)||String.isNullOrEmpty(Path.getFileName($p0));if($1){var $4=Path.combinePath($p0,$0);this.setProperty('checkedout_path',$4,null);return $4;}else{this.setProperty('checkedout_path',$p0,null);return $p0;}},$26:function($p0,$p1,$p2){var $0=this.$25($p0,$p2);var $1=Type.safeCast(this.serverConnection,Aras.IOM.ServerConnectionBase);if($1!=null){$1.$8(this,$0,true,$p1);}else{this.serverConnection.DownloadFile(this,$0,true);}return this;},setNewID:function(){this.setID(this.getNewID());},getNewID:function(){return Aras.IOM.Innovator.$3();},$27:null,$28:function($p0,$p1,$p2){if(!this.$12(4)&&($p2&&!this.$12(32))){throw new Error('Not a single item');}if(!this.$12(1)){throw new Error(String.format(Aras.IOM.Item.$6,"'this' item"));}if(!$p1.$12(4)){throw new Error('The argument passed to the method is not a single item');}var $0=this.node.selectSingleNode($p0);if($0==null){$0=this.node.appendChild(this.dom.createElement($p0));}var $1=$0.selectSingleNode('Item');if($1!=null){$p1.node=$p1.node.cloneNode(true);$0.replaceChild($p1.node,$1);}else{$0.text='';$p1.node=$0.appendChild($p1.node.cloneNode(true));}$p1.dom=this.dom;},$29:function($p0,$p1){var $0;if($p1!=null){var $2=this.$27.getI18NSessionContext();if($2!=null&&$p1!==$2.GetLanguageCode()){$0=this.dom.createNode(1,'i18n'+':'+$p0,'http://www.aras.com/I18N');}else{$0=this.dom.createElement($p0);}}else{$0=this.dom.createElement($p0);}var $1=this.node.appendChild($0);return $1;},$2A:function($p0,$p1){var $0;$0=String.format('./{0}',$p0);if($p1!=null){var $2=this.$27.getI18NSessionContext();if($2!=null){$0=String.format(($2.GetLanguageCode()===$p1)?"./*[local-name()='{0}' and (namespace-uri()='{1}' or name()='{0}') and @xml:lang='{2}']":"./*[local-name()='{0}' and namespace-uri()='{1}' and @xml:lang='{2}']",$p0,'http://www.aras.com/I18N',$p1);}}var $1;$1=this.node.selectSingleNode($0);return $1;},$2B:function($p0){if(!this.$12(4)){throw new Error('Not a single item');}if(String.equals($p0,'id',StringComparison.ordinalIgnoreCase)){return true;}return (this.node.selectSingleNode($p0)!=null);},getLogicalChildren:function(){if(!this.$12(4)&&!this.$12(32)){throw new Error('Not a single item');}var $0=Aras.IOM.Item.$0(this.serverConnection,null,null,null);$0.dom=this.dom;$0.node=null;$0.nodeList=this.node.selectNodes("./*[local-name()='and' or local-name()='or' or local-name()='not']");return $0;},instantiateWorkflow:function(workflowMapID){if(workflowMapID==null||!workflowMapID.trim().length){throw new Error(Aras.IOM.Item.$2);}if(!this.$12(4)){throw new Error('Not a single item');}if(this.isNew()){throw new Error(Aras.IOM.Item.$3);}var $0=this.$31();var $1=this.newItem(this.getType(),null);$1.setAction(Aras.IOM.Item.$4);$1.setID($0);$1.setProperty('WorkflowMap',workflowMapID,null);var $2=$1.apply(Aras.IOM.Item.$4);if($2.isError()){return $2;}var $3=$2;$1=this.newItem('Workflow','add');$1.setProperty('locked_by_id',this.serverConnection.getUserID(),null);$1.setProperty('source_id',$0,null);$1.setProperty('related_id',$3.getID(),null);$1.setProperty('source_type',this.getAttribute('typeId'),null);$2=$1.apply();return ($2.isError())?$2:$3;},toString:function(){return Aras.IOM.XmlExtension.getXml(this.dom);},$2C:null,setThisMethodImplementation:function(thisMethodImplemenation){this.$2C=thisMethodImplemenation;},thisMethod:function(inDom,inArgs){if(this.$2C==null){return null;}return this.$2C.call(this,inDom,inArgs);},createRelationship:function(type,action){return this.$2D('Relationships',type,action,false);},createPropertyItem:function(propName,type,action){return this.$2D(propName,type,action,true);},createRelatedItem:function(type,action){return this.$2D('related_id',type,action,true);},$2D:function($p0,$p1,$p2,$p3){if(!this.$12(4)){throw new Error('Not a single item');}if(!this.$12(1)){throw new Error(String.format(Aras.IOM.Item.$6,"'this' item"));}var $0=this.node.selectSingleNode($p0)||this.node.appendChild(this.dom.createElement($p0));var $1;if($p3){$1=$0.selectSingleNode('Item');if($1!=null){$0.removeChild($1);}}$1=$0.appendChild(this.dom.createElement('Item'));$1.setAttribute('isNew','1');$1.setAttribute('isTemp','1');$1.setAttribute('type',$p1);$1.setAttribute('action',$p2);var $2=Aras.IOM.Item.$0(this.serverConnection,null,null,null);$2.dom=this.dom;$2.node=$1;return $2;},$2E:function(){var $0=this.$16();if($0.isError()){throw new Error($0.getErrorDetail());}return $0.getProperty('default_vault');},attachPhysicalFile:function(filePath,vaultServerId){this.$2F(filePath,vaultServerId);},$2F:function($p0,$p1){if(ss.isNullOrUndefined($p1)){$p1=this.$2E();}if(!this.$12(4)){throw new Error('Not a single item');}this.$30();this.$31();if($p1==null||!$p1.trim().length){throw new Error('Specified vault ID is not valid');}aras.vault.addFileToList(this.getID(), arguments[0]);this.setProperty("actual_filename", arguments[0].name, null);var $0=this.node;var $1=$0.selectSingleNode('Relationships');if($1==null){$1=$0.appendChild(this.dom.createElement('Relationships'));}else{var $4=$1.selectNodes("Item[@type='Located' and related_id!='"+$p1+"']");if($4!=null){var $enum1=ss.IEnumerator.getEnumerator($4);while($enum1.moveNext()){var $5=$enum1.current;$1.removeChild($5);}}}var $2=$1.selectSingleNode("Item[@type='Located' and related_id='"+$p1+"']");if($2==null){$2=$1.appendChild(this.dom.createElement('Item'));$2.setAttribute('type','Located');}else{var $6=$2.selectSingleNode('file_version');if($6!=null){$2.removeChild($6);}}if(!Aras.IOM.InternalUtils.$0($2,'action').length){if(Aras.IOM.InternalUtils.$0($0,'action')==='add'){$2.setAttribute('action','add');}else{$2.setAttribute('action','merge');}}if(!Aras.IOM.InternalUtils.$0($2,'id').length&&!Aras.IOM.InternalUtils.$0($2,'where').length){$2.setAttribute('where',"related_id='"+$p1+"'");}var $3=$2.appendChild(this.dom.createElement('related_id'));$3.text=$p1;},$30:function(){var $0=this.$32();if('File'!==$0){throw new Error("The item is not of type 'File'");}return $0;},$31:function(){var $0=this.getID();if(String.isNullOrEmpty($0)){throw new Error('Item ID is not set');}return $0;},$32:function(){var $0=this.getType();if(String.isNullOrEmpty($0)){throw new Error('Item type is not set');}return $0;},getId:function(){return this.getID();},applyStylesheet:function(xslStylesheet,type){if(type==null){throw new Error('type');}var $0=new XmlDocument();var $1=type.trim().toLowerCase();if($1==='url'){var $3=xslStylesheet;$0.load($3);if($0.xml==null||!$0.xml){$0.loadUrl($3);}}else if($1==='text'){Aras.IOM.InternalUtils.loadXmlFromString($0,xslStylesheet);}var $2;$2=new XmlDocument();Aras.IOM.InternalUtils.loadXmlFromString($2,this.dom.xml);return $2.transformNode($0);},applyAsync:function(action,argsObject){var $0=Type.safeCast(action,String);if(null===$0&&null!==action){argsObject=Type.safeCast(action,Object);}this.$14($0,argsObject);var $1=Type.safeCast(this.serverConnection,Aras.IOM.InnovatorServerConnector);if($1.get_$3()&&this.$1B()){return this.$33();}var $2=this.newXMLDocument();Aras.IOM.InternalUtils.loadXmlFromString($2,Aras.IOM.XmlExtension.getXml(this.node));return $1.callActionAsync('ApplyItem',$2).then(ss.Delegate.create(this,function($p1_0){
var $1_0=Aras.IOM.Item.$0(this.serverConnection,null,null,null);$1_0.dom=$p1_0;if(null===$1_0.dom.selectSingleNode(Aras.IOM.Item.xPathFault+'/faultcode')){$1_0.$11();}return $1_0;}));},$33:function(){var $0=this.$19();var $1=new ss.StringBuilder();if(null!==this.node){$1.append(Aras.IOM.XmlExtension.getXml(this.node));}else{for(var $5=0,$6=this.nodeList.length;$5<$6;$5++){$1.append(Aras.IOM.XmlExtension.getXml(this.nodeList[$5]));}}var $2=this.$1A();var $3=this.$17($2);var $4=Type.safeCast(this.serverConnection,Aras.IOM.InnovatorServerConnector);return $4.$10('ApplyAML',$1.toString(),$0,$3,$2).then(ss.Delegate.create(this,function($p1_0){
var $1_0=this.newItem();$1_0.loadAML($p1_0);return $1_0;}));}}
Aras.IOM.InnovatorServerConnector=function(parentArasObj){Aras.IOM.InnovatorServerConnector.initializeBase(this);this.$E=parentArasObj;if(ss.isNullOrUndefined(this.$E)){this.$E=window.aras || parent.aras || parent.parent.aras;}}
Aras.IOM.InnovatorServerConnector.createConnection=function(loginName,md5Password){var $0=new Aras.IOM.InnovatorServerConnector(null);$0.loginWithCredentials(loginName,md5Password);return $0;}
Aras.IOM.InnovatorServerConnector.prototype={$E:null,getDatabases:function(){var $0=this.$E.XmlHttpRequestManager.CreateRequest();var $1=this.$E.getServerBaseURL();$0.open('GET',$1+'DBList.aspx',false);$0.send(null);var $2=new XmlDocument();Aras.IOM.InternalUtils.loadXmlFromString($2,$0.responseText);var $3=$2.selectNodes('DBList/DB/@id');var $4=new Array($3.length);for(var $5=0;$5<$3.length;$5++){$4[$5]=$3[$5].text;}return $4;},CallAction:function(actionName,inDOM,outDOM){var $0=null;var $1=inDOM.documentElement;if($1.nodeName==='Item'){var $2=$1.getAttribute('action');if($2==='purge'||$2==='delete'||$2==='update'||$2==='version'||$2==='add'){var iomCache = new IOMCache(this.$E);(iomCache.apply($1)).then(function($p1_0){
return $0=$p1_0;});}}if($0!=null){Aras.IOM.InternalUtils.loadXmlFromString(outDOM,'<Result>'+$0.xml+'</Result>');}else{var res = this.$E.soapSend(actionName, inDOM.xml);var $3=res.getResponseText();Aras.IOM.InternalUtils.loadXmlFromString(outDOM,$3);}},callActionAsync:function(actionName,inDOM){var $0=Promise.resolve(null);var $1=inDOM.documentElement;var $2=$1.getAttribute('action');if($1.nodeName==='Item'&&($2==='purge'||$2==='delete'||$2==='update'||$2==='version'||$2==='add')){var iomCache = new IOMCache(this.$E);$0=iomCache.apply($1, true);}return $0.then(function($p1_0){
if($p1_0!=null){return String.concat('<Result>',($p1_0).xml,'</Result>');}return TopWindowHelper.getMostTopWindowWithAras(window).ArasModules.soap(inDOM.xml, {method: actionName, async: true});}).then(function($p1_0){
return Aras.IOM.InternalUtils.createAndLoadXmlDocument((Type.canCast($p1_0,String))?$p1_0:($p1_0).xml);});},$10:function($p0,$p1,$p2,$p3,$p4){var $0=this.$A($p0);if(!ss.isNullOrUndefined($p4)){$0.add(new Aras.Utils.HeaderClientData('VAULTID',$p4));}var $1=String.format('{0}<AML>{1}</AML>{2}',Aras.SoapConstants._Soap.$6,$p1,Aras.SoapConstants._Soap.$7);$0.add(new Aras.Utils.HeaderClientData('XMLdata',$1));var $2=new FileUpload(TopWindowHelper.getMostTopWindowWithAras(window).aras,this.$7($p3));return $2.uploadFiles($p2,$0,true).then(function($p1_0){
return $p1_0;});},$C:function($p0){var $0=this.$E.OAuthClient.getAuthorizationHeader();var $1=this.$E.OAuthClient.authorizationHeaderName;var $2=$0[$1];$p0.add(new Aras.Utils.HeaderClientData($1,$2));},debugLog:function(reason,msg){throw new Error('NotImplementedException');},debugLogP:function(){throw new Error('NotImplementedException');},getUserID:function(){var $0=this.$E.getUserID();if(ss.isNullOrUndefined($0)){throw new Error('Not logged in');}return $0;},getDatabaseName:function(){return this.$E.getDatabase();},getLicenseInfo:function(issuer,addon_name){var $0=new XmlDocument();var $1=new XmlDocument();Aras.IOM.InternalUtils.loadXmlFromString($0,'<Item/>');if(!String.isNullOrEmpty(issuer)){var $6=$0.createElement('issuer');$6.text=issuer;$0.documentElement.appendChild($6);}if(String.isNullOrEmpty(addon_name)){var $7=$0.createElement('keyed_name');$7.text=addon_name;$0.documentElement.appendChild($7);}var $2=this.$E.getServerBaseURL();var $3=this.$E.soapSend('GetLicenseInfo', $0.xml, $2+'License.aspx', null, null, null, null, true);var $4=$3.getResponseText();Aras.IOM.InternalUtils.loadXmlFromString($1,$4);var $5=$1.selectSingleNode('//Result/*');if($5==null||!$5.xml){return null;}else{return $5.xml;}},getOperatingParameter:function(name,defaultvalue){throw new Error('NotImplementedException');},getSrvContext:function(){throw new Error('NotImplementedException');},GetValidateUserXmlResult:function(){return this.$E.getCommonPropertyValue('ValidateUserXmlResult');},getUserInfo:function(){var $0=this.$E.IomFactory;var $1=this.getUserID();var $2=this.$E.MetadataCache.CreateCacheKey('getUserInfo', $1);var $3=this.$E.MetadataCache.GetItem($2);if($3==null){var $4=Aras.IOM.InnovatorServerConnector.callBaseMethod(this, 'getUserInfo');$3=$0.CreateCacheableContainer($4,$1);this.$E.MetadataCache.SetItem($2, $3);}return $3.Content();},getFileUrl:function(fileId,type){var $0=Aras.IOM.InnovatorServerConnector.callBaseMethod(this, 'getFileUrl',[fileId,0]);if(type===1){var $1=new AuthenticationBrokerClient();var $2=$1.GetFileDownloadToken(fileId);$0+='&token='+$2;}return $0;},getFileUrls:function(fileIds,type){var $0=Aras.IOM.InnovatorServerConnector.callBaseMethod(this, 'getFileUrls',[fileIds,0]);if(type===1){var $1=new AuthenticationBrokerClient();var $2=$1.GetFilesDownloadTokens(fileIds);for(var $3=0;$3<fileIds.length;$3++){$0[$3]+='&token='+$2[$3];}}return $0;},getLicenseManagerWebService:function(){return new Aras.IOME.Licensing.IOMScriptSharp$3();},get_userName:function(){return this.$E.getLoginName();},get_userPassword:function(){return this.$E.getPassword();},loginDefault:function(){InnovatorServerTests.Test._testHelper._logOn(InnovatorServerTests.Test.ConnectionInfo._adminLoginName, InnovatorServerTests.Test.ConnectionInfo._adminPasswordHash, InnovatorServerTests.Test.ConnectionInfo._databaseAlias, InnovatorServerTests.Test.ConnectionInfo._innovatorServerUrl, '');},login:function(){this.loginDefault();return Aras.IOM.InnovatorServerConnector.callBaseMethod(this, 'getUserInfo');},loginWithCredentials:function(loginName,password){var $0=Aras.IOM.InnovatorServerConnector.$F.test(password);var $1=($0)?password:ArasModules.cryptohash.MD5(password).toString();InnovatorServerTests.Test._testHelper._logOn(loginName, $1, InnovatorServerTests.Test.ConnectionInfo._databaseAlias, InnovatorServerTests.Test.ConnectionInfo._innovatorServerUrl, '');return Aras.IOM.InnovatorServerConnector.callBaseMethod(this, 'getUserInfo');},logout:function(unlockOnLogout){this.$E.logout();;},$11:null,get_innovator:function(){return this.$11||(this.$11=new Aras.IOM.IomFactory().CreateInnovator(this));}}
Aras.IOM.ServerConnectionBase=function(){this.$2=Aras.I18NUtils.I18NSystemInfo.get_$2();}
Aras.IOM.ServerConnectionBase.prototype={$0:function($p0,$p1){return null;},cachedUserInfo:null,$1:null,get_locale:function(){return this.$1;},set_locale:function(value){this.$1=value;return value;},get_timeZoneName:function(){return this.$2;},set_timeZoneName:function(value){this.$2=value;return value;},get_$3:function(){return true;},$4:function($p0){var $0=$p0.getRelationships('Located');var $1=$0.getItemCount();if(!$1){return null;}else if($1===1){return $0.getItemByIndex(0).getRelatedItem();}var $2=0;var $3=0;for($3=0;$3<$1;$3++){var $5=$0.getItemByIndex($3);var $6=parseInt($5.getProperty('file_version'));if($6>$2){$2=$6;}}var $4=this.$5($p0,$0);for($3=0;$3<$4.length;$3++){var $7=$4[$3];var $8=parseInt($7.getProperty('file_version'));if($8===$2){return $7.getRelatedItem();}}return null;},$5:function($p0,$p1){var $0=$p1.getItemCount();var $1=0;var $2=[];var $3=this.getUserInfo();if($3.isError()){throw new Error('Error getting user info: '+$3.toString());}var $4=$3.getRelationships('ReadPriority');var $5=$4.getItemCount();for($1=0;$1<$5;$1++){var $8=$4.getItemByIndex($1).getRelatedItem();for(var $9=0;$9<$0;$9++){var $A=$p1.getItemByIndex($9);if($8.getID()===$A.getRelatedItem().getID()){$2.add($A);break;}}}var $6=false;var $7=$3.getPropertyItem('default_vault');for($1=0;$1<$2.length;$1++){if($2[$1].getRelatedItem().getID()===$7.getID()){$6=true;break;}}if(!$6){for($1=0;$1<$0;$1++){var $B=$p1.getItemByIndex($1);if($7.getID()===$B.getRelatedItem().getID()){$2.add($B);break;}}}for($1=0;$1<$0;$1++){var $C=$p1.getItemByIndex($1);var $D=false;for(var $E=0;$E<$2.length;$E++){if($2[$E].getID()===$C.getID()){$D=true;break;}}if(!$D){$2.add($C);}}return $2;},$6:function($p0,$p1){var $0=$p1.getProperty('vault_url');if(String.isNullOrEmpty($0)){return null;}$0=this.$7($0);if($0==null){return null;}var $1=$p1.getID();var $2;var $3=String.format('{0}?dbName={1}&fileId={2}&fileName={3}&vaultId={4}',$0,HttpUtility.urlEncode(this.GetDatabaseName()),HttpUtility.urlEncode($p0.getID()),HttpUtility.urlEncode($p0.getProperty('filename')),HttpUtility.urlEncode($1));$2=$3;return $2;},$7:function($p0){var $0=$p0;if($p0.indexOf('$[')!==-1){var $1=new XmlDocument();var $2=new XmlDocument();Aras.IOM.InternalUtils.loadXmlFromString($1,'<url>'+$p0+'</url>');Aras.IOM.InternalUtils.loadXmlFromString($2,'<Empty />');this.CallAction('TransformVaultServerURL',$1,$2);if($2.selectSingleNode(Aras.IOM.Item.xPathFault)==null){$0=$2.selectSingleNode(Aras.IOM.Item.xPathResult).text;}}return $0;},DownloadFile:function(fileItem,fileName,overwrite){this.$8(fileItem,fileName,overwrite,null);},$8:function($p0,$p1,$p2,$p3){var $0=$p0.getID();if($p0.getAttribute('__aras_file_has_all_located__')!=='1'){var $5=Aras.IOM.Item.$0(this,'File',null,'full');$5.loadAML("<Item type='File' action='get' select='id,filename'>"+'<Relationships>'+"<Item type='Located' select='id,related_id,file_version' action='get'>"+'<related_id>'+"<Item type='Vault' select='id,vault_url' action='get'>"+'</Item>'+'</related_id>'+'</Item>'+'</Relationships>'+'</Item>');$5.setID($0);var $6=$5.apply();if($6.isError()){throw new Error('Error getting file: '+$6.getErrorString());}$p0=$6;}else{$p0.removeAttribute('__aras_file_has_all_located__');}var $1=this.$4($p0);if($1==null){throw new Error('Vault location of the file is unknown');}var $2=this.$6($p0,$1);var $3=this.$A(null);$3.add(new Aras.Utils.HeaderClientData('VAULTID',$1.getID()));if($p3!=null&&$p3.$0===$1.getID()){$3.add(new Aras.Utils.HeaderClientData('TRANSACTIONID',$p3.id));}var $4=this.getFileUrl($0,1);$4+='&contentDispositionAttachment=1';TopWindowHelper.getMostTopWindowWithAras(window).ArasModules.vault._downloadHelper($4, false); return;FileDownload.downloadFile($2,$p1,$3,null);},getUserInfo:function(){if(this.cachedUserInfo!=null){return this.cachedUserInfo;}var $0=Aras.IOM.Item.$0(this,'User',null,'full');var $1=this.getUserID();var $2="<Item type='User' action='get' select='default_vault' expand='1'><id>"+$1+'</id><Relationships>'+"<Item type='ReadPriority' action='get' select='priority, related_id' expand='1' orderBy='priority'/></Relationships></Item>";$0.loadAML($2);$0=$0.apply();if($0.isError()){$2="<Item type='User' action='get' select='default_vault' expand='1'><id>"+$1+'</id></Item>';$0.loadAML($2);$0=$0.apply();}this.cachedUserInfo=$0;return $0;},GetFromCache:function(key){throw new Error('Not Implemented');},InsertIntoCache:function(key,value,path){throw new Error('Not Implemented');},getFileUrl:function(fileId,type){if(fileId==null){throw new Error('fileId');}return this.$9([fileId])[0];},getFileUrls:function(fileIds,type){if(fileIds==null){throw new Error('fileIds');}if(!fileIds.length){throw new Error('List cannot be empty. Parameter name: fileIds');}if(!!type){throw new Error(type.toString());}var $0=new Array(fileIds.length);for(var $2=0;$2<fileIds.length;$2++){$0[$2]=fileIds[$2].toString();}var $1=this.$9($0);return [$1];},$9:function($p0){var $0=Aras.IOM.Item.$0(this,'File',null,'full');$0.loadAML("<Item type='File' action='get' select='id,filename'>"+'<Relationships>'+"<Item type='Located' select='id,related_id,file_version' action='get'>"+'<related_id>'+"<Item type='Vault' select='id,vault_url' action='get'>"+'</Item>'+'</related_id>'+'</Item>'+'</Relationships>'+'</Item>');var $1=null;for(var $4=0;$4<$p0.length;$4++){var $5=$p0[$4];if($1==null){$1=$5;}else{$1+=','+$5;}}$0.setProperty('id',$1,null);$0.setPropertyCondition('id','in',null);var $2=$0.apply();if($2.isError()){throw new Error('Error getting files: '+$2.getErrorString());}var $3=new Array($p0.length);for(var $6=0;$6<$p0.length;$6++){var $7=$2.getItemsByXPath(Aras.IOM.Item.xPathResult+'/Item[id="'+$p0[$6]+'"]');var $8=this.$4($7);if($8==null){throw new Error('Vault location of the file is unknown');}$3[$6]=this.$6($7,$8);}return $3;},$A:function($p0){var $0=this.$B($p0);this.$C($0);return $0;},$B:function($p0){var $0=[];if(!String.isNullOrEmpty($p0)){$0.add(new Aras.Utils.HeaderClientData('SOAPACTION',$p0));}$0.add(new Aras.Utils.HeaderClientData('LOCALE',this.get_locale()));$0.add(new Aras.Utils.HeaderClientData('TIMEZONE_NAME',this.get_timeZoneName()));return $0;},$C:function($p0){$p0.add(new Aras.Utils.HeaderClientData('AUTHUSER',this.get_userName()));$p0.add(new Aras.Utils.HeaderClientData('AUTHPASSWORD',this.get_userPassword()));$p0.add(new Aras.Utils.HeaderClientData('DATABASE',this.GetDatabaseName()));},$D:function($p0,$p1,$p2,$p3,$p4,$p5){var $0=this.$A($p0);if(!ss.isNullOrUndefined($p4)){$0.add(new Aras.Utils.HeaderClientData('VAULTID',$p4));}if(!ss.isNullOrUndefined($p5)){$0.add(new Aras.Utils.HeaderClientData('TRANSACTIONID',$p5.id));}var $1;$1=String.format('{0}<AML>{1}</AML>{2}',Aras.SoapConstants._Soap.$6,$p2,Aras.SoapConstants._Soap.$7);$0.add(new Aras.Utils.HeaderClientData('XMLdata',$1));$p3=this.$7($p3);var $2=new FileUpload(TopWindowHelper.getMostTopWindowWithAras(window).aras,$p3);var $3=$2.uploadFiles($p1,$0);return $3;}}
Aras.IOM.IOMScriptSharp$6=function(innovatorServerUrl){Aras.IOM.IOMScriptSharp$6.initializeBase(this,[innovatorServerUrl,'','','','','']);}
Aras.IOM.IOMScriptSharp$6.prototype={getUserID:function(){throw new Error('Operation not supported, create new instance of Aras.IOM.HttpServerConnection and specify db name, login and password');},GetDatabaseName:function(){throw new Error('Operation not supported, create new instance of Aras.IOM.HttpServerConnection and specify db name, login and password');},GetValidateUserXmlResult:function(){throw new Error('Operation not supported, create new instance of Aras.IOM.HttpServerConnection and specify db name, login and password');},Login:function(){throw new Error('Operation not supported, create new instance of Aras.IOM.HttpServerConnection and specify db name, login and password');},Logout:function($p0){throw new Error('Operation not supported, create new instance of Aras.IOM.HttpServerConnection and specify db name, login and password');}}
Aras.IOM.WinAuthHttpServerConnection=function(innovatorServerUrl,database){Aras.IOM.WinAuthHttpServerConnection.initializeBase(this,[innovatorServerUrl,database,'','','','']);}
Aras.IOM.WinAuthHttpServerConnection.prototype={Login:function(){var $0=Aras.IOM.InternalUtils.createXmlDocument();var $1=Aras.IOM.InternalUtils.createXmlDocument();Aras.IOM.InternalUtils.loadXmlFromString($0,'<Item/>');Aras.IOM.InternalUtils.loadXmlFromString($1,'<Empty/>');var $2=this.$E.toLowerCase().indexOf('/server/innovatorserver.aspx');var $3=this.$E.substring(0,$2)+'/Client/scripts/IOMLogin.aspx';this.callActionImpl('',$0,$1,$3,false);var $4=$1.selectSingleNode('//Result');if($4==null){var $7='Failed to connect to IOMLogin.aspx. Either IOMLogin.aspx is not setup to use integrated Windows authentication or the authentication failed.';return new Aras.IOM.Innovator(this).newError($7);}var $5=$4.selectSingleNode('user').text;var $6=$4.selectSingleNode('password').text;if(!$6.trim().length){return new Aras.IOM.Innovator(this).newError("Failed to authenticate with Innovator server '"+this.$E+"'. Original error: "+$5);}this.$1A=new Aras.IOM.IOMScriptSharp$5($5,$6);return Aras.IOM.WinAuthHttpServerConnection.callBaseMethod(this, 'Login');}}
Type.registerNamespace('Aras.Utils');Aras.Utils.IClientData=function(){};Aras.Utils.IClientData.registerInterface('Aras.Utils.IClientData');Aras.Utils.HeaderClientData=function(name,value){this.$1=name;this.$0=value;}
Aras.Utils.HeaderClientData.prototype={$0:null,$1:null,get_value:function(){return this.$0;},get_name:function(){return this.$1;}}
Type.registerNamespace('Aras.I18NUtils');Aras.I18NUtils.Intl=function(){this.number=new Aras.I18NUtils.ArasNumber();}
Aras.I18NUtils.ArasNumber=function(){}
Aras.I18NUtils.ArasNumber.prototype={parseInt:function(numberStr){return 0;},parseFloat:function(numberStr,maximumIntegerDigits){return 0;},toString:function(number){return '';},format:function(number,options){return '';}}
Aras.I18NUtils._I18NConverter=function(){}
Aras.I18NUtils._I18NConverter.$8=function($p0){if($p0==null){$p0='';}$p0=$p0.replaceAll(' ','_');$p0=String.format('{0}_',$p0);if($p0===32||$p0==='boolean_'){return 32;}if($p0===16384||$p0==='color_'){return 16384;}if($p0===8192||$p0==='color_list_'){return 8192;}if($p0===64||$p0==='date_'){return 64;}if($p0===16||$p0==='decimal_'){return 16;}if($p0===32768||$p0==='federated_'){return 32768;}if($p0===4096||$p0==='filter_list_'){return 4096;}if($p0===8||$p0==='float_'){return 8;}if($p0===131072||$p0==='foreign_'){return 131072;}if($p0===65536||$p0==='formatted_text_'){return 65536;}if($p0===128||$p0==='image_'){return 128;}if($p0===4||$p0==='integer_'){return 4;}if($p0===1024||$p0==='item_'){return 1024;}if($p0===2048||$p0==='list_'){return 2048;}if($p0===256||$p0==='md5_'){return 256;}if($p0===262144||$p0==='ml_string_'){return 262144;}if($p0===512||$p0==='sequence_'){return 512;}if($p0===1||$p0==='string_'){return 1;}if($p0===2||$p0==='text_'){return 2;}return 0;}
Aras.I18NUtils._I18NConverter.$9=function($p0){if($p0==null){$p0='';}if($p0===(4)||$p0==='long_date'){return 4;}if($p0===(8)||$p0==='long_date_time'){return 8;}if($p0===(1)||$p0==='short_date'){return 1;}if($p0===(2)||$p0==='short_date_time'){return 2;}return 0;}
Aras.I18NUtils._I18NConverter.$B=function($p0,$p1){var $0;try{$0=CultureInfo.CreateSpecificCulture($p1);}catch($4){$0=CultureInfo.InvariantCulture;}var $1=$0.DateTimeFormat;var $2=$1.ShortDatePattern;var $3=Aras.I18NUtils._I18NConverter.$9($p0);switch($3){case 1:$2=$1.ShortDatePattern;break;case 2:$2=String.format('{0} {1}',$1.ShortDatePattern,$1.LongTimePattern);break;case 4:$2=$1.LongDatePattern;break;case 8:$2=String.format('{0} {1}',$1.LongDatePattern,$1.LongTimePattern);break;default:switch($p0){case 'long_time':$2=$1.LongTimePattern;break;case 'short_time':$2=$1.ShortTimePattern;break;}break;}return $2;}
Aras.I18NUtils._I18NConverter.prototype={$3:null,get_$4:function(){return (this.$3==null)?CultureInfo.InvariantCulture:this.$3;},set_$4:function($p0){this.$3=$p0;return $p0;},$6:null,get_$7:function(){return this.$6;},set_$7:function($p0){this.$6=$p0;if(this.$6==null){this.$6='';}this.set_$4(Type.safeCast(Aras.I18NUtils._I18NConverter.$5[this.$6],CultureInfo));if(this.$3==null){try{this.set_$4(CultureInfo.CreateSpecificCulture(this.$6));}catch($0){this.set_$4(CultureInfo.InvariantCulture);this.$6=this.get_$4().Name;}Aras.I18NUtils._I18NConverter.$5[this.$6]=this.get_$4();}return $p0;},$A:function($p0,$p1,$p2,$p3,$p4,$p5){if($p0==null){return null;}var $0=$p0;var $1=CultureInfo.InvariantCulture;this.set_$7($p4);var $2=this.get_$4();var $3=$2.DateTimeFormat;var $4=Aras.I18NUtils._I18NConverter.$8($p1);switch($4){case 64:var $5=Aras.I18NUtils._I18NConverter.$9($p3);if(!!$5&&!String.isNullOrEmpty($p3)){$p3=Aras.I18NUtils._I18NConverter.$B($p3,$2.Name);}if($p2){var $7;var $8=false;if(String.isNullOrEmpty($p3)){$7=$3.Parse($p0,null,this.get_$7());var $9=new Date(Date.UTC($7.getFullYear(),$7.getMonth(),$7.getDate(),$7.getHours(),$7.getMinutes(),$7.getSeconds(),$7.getMilliseconds()));}else{$7=$3.Parse($p0,$p3,$2.Name);if(ss.isNullOrUndefined($7)){return null;}if($p3.toLowerCase().indexOf('z')>-1){$8=true;}}if($8){$7=new Date(Date.UTC($7.getFullYear(),$7.getMonth(),$7.getDate(),$7.getHours(),$7.getMinutes(),$7.getSeconds(),$7.getMilliseconds()));var $A=$3.OffsetBetweenTimeZones($7,$p5,null);$7.setTime($7.getTime()+$A*1000*60);}$0=$3.Format($7,'yyyy-MM-ddTHH:mm:ss',null);}else{var $B=$3.Parse($p0,'yyyy-MM-ddTHH:mm:ss');if(ss.isNullOrUndefined($B)){$B=$3.Parse($p0,'yyyy-MM-dd');if(ss.isNullOrUndefined($B)){return null;}}$0=$3.Format($B,$p3,this.get_$7());}break;case 16:if(Type.getInstanceType($p0)===String&&$p0.toLowerCase()==='infinity'){return $p0;}var $6=ArasModules.intl.number.parseFloat($p0,0);if(isNaN($6)){$0=null;}else{if($p2){$0=ArasModules.intl.number.toString($6);}else{var $C=(!!$p3)?$p3.split('.'):[];$0=ArasModules.intl.number.format($6,{minimumFractionDigits:($C.length===2)?($C[1]).length:0});}}break;case 8:if(Type.getInstanceType($p0)===String&&$p0.toLowerCase()==='infinity'){return $p0;}$6=ArasModules.intl.number.parseFloat($p0,0);if($p2){$0=ArasModules.intl.number.toString($6);}else{$0=ArasModules.intl.number.format($6,0);}break;}return $0;}}
Aras.I18NUtils.I18NSystemInfo=function(){}
Aras.I18NUtils.I18NSystemInfo.get_$0=function(){return ss.CultureInfo.CurrentCulture;}
Aras.I18NUtils.I18NSystemInfo.get_$1=function(){return ss.CultureInfo.CurrentCulture;}
Aras.I18NUtils.I18NSystemInfo.get_$2=function(){return 'Kaliningrad Standard Time';}
Type.registerNamespace('Aras.IOME');Aras.IOME.ICacheable=function(){};Aras.IOME.ICacheable.registerInterface('Aras.IOME.ICacheable');Aras.IOME.CacheableContainer=function(value,dependenciesSource){this.set_$0(value);this.$1=Aras.IOME.CacheableContainer.$2(dependenciesSource);}
Aras.IOME.CacheableContainer.$2=function($p0){var $0={};Aras.IOME.ItemCache.$3($p0,$0);var $1=0;var $2=new Array(Object.getKeyCount($0)+1);var $enum1=ss.IEnumerator.getEnumerator(Object.keys($0));while($enum1.moveNext()){var $3=$enum1.current;$2[$1]=$3;$1++;}return $2;}
Aras.IOME.CacheableContainer.prototype={get_$0:function(){return this.content;},set_$0:function($p0){this.content=$p0;return $p0;},$1:null,content:null,Content:function(){return this.content;},getGuidsItemDependsOn:function(){return this.$1;}}
Aras.IOME._KeyComparator=function(){}
Aras.IOME._KeyComparator.$0=function($p0){var $0='';var $enum1=ss.IEnumerator.getEnumerator($p0);while($enum1.moveNext()){var $1=$enum1.current;$0+=$1.toString();}return $0;}
Aras.IOME._KeyComparator.prototype={$1:function($p0,$p1){if($p0==null){throw new Error('x');}var $0=Type.safeCast($p0,Array);if($0!=null){var $3=$0;var $4=$p1;var $5=Aras.IOME._KeyComparator.$0($3);var $6=Aras.IOME._KeyComparator.$0($4);return String.compare($5,$6,StringComparison.ordinalIgnoreCase);}var $1=$p0.toString();var $2=$p0.toString();return String.compare($1,$2,StringComparison.ordinalIgnoreCase);}}
Aras.IOME.ArrayListComparer=function(){}
Aras.IOME.ArrayListComparer.prototype={equals:function(x,y){var $0,$1;var $2,$3;$0=x;$1=y;$3=$0.length;if($3<$1.length||$3>$1.length){return false;}for($2=0;$2<$3;++$2){if($0[$2]!==$1[$2]){return false;}}return true;},getHashCode:function(obj){var $0=obj;var $1,$2,$3;$2=$0.length;$3=0;for($1=0;$1<$2;++$1){$3=$3^this.$0($0[$1].toString());}return $3;},$0:function($p0){var $0=0;if(!$p0.length){return $0;}for(var $1=0;$1<$p0.length;$1++){var $2=$p0.charCodeAt($1);$0=(($0<<5)-$0)+$2;$0=$0&$0;}return $0;}}
Aras.IOME.ItemCache=function(){this.$0={};this.$1={};}
Aras.IOME.ItemCache.$3=function($p0,$p1){if($p0==null){return;}if(typeof($p0)==='object'){if(('getAttribute' in $p0)){Aras.IOME.ItemCache.$4($p0,$p1);return;}if(('innerText' in $p0)){Aras.IOME.ItemCache.$5($p0,$p1);return;}}var $0=Type.safeCast($p0,Aras.IOME.ICacheable);if($0!=null){var $3=$0.getGuidsItemDependsOn();for(var $4=0;$4<$3.length;$4++){if(!String.isNullOrEmpty($3[$4])){$p1[$3[$4]]=true;}}return;}var $1=Type.safeCast($p0,String);if($1!=null){if(Aras.IOME.ItemCache.$7($1)){$p1[$1]=true;}return;}var $2=Type.safeCast($p0,Array);if($2!=null){var $enum1=ss.IEnumerator.getEnumerator($2);while($enum1.moveNext()){var $5=$enum1.current;Aras.IOME.ItemCache.$3($5,$p1);}return;}}
Aras.IOME.ItemCache.$4=function($p0,$p1){var $0='';if($p0.getAttribute('id')!=null){$0=$p0.getAttribute('id').toString();if(Aras.IOME.ItemCache.$7($0)){$p1[$0]=true;}}var $enum1=ss.IEnumerator.getEnumerator($p0.selectNodes('.//*/@id'));while($enum1.moveNext()){var $1=$enum1.current;$0=$1.text;if(Aras.IOME.ItemCache.$7($0)){$p1[$0]=true;}}var $enum2=ss.IEnumerator.getEnumerator($p0.selectNodes('descendant::text()[string-length(.)=32]'));while($enum2.moveNext()){var $2=$enum2.current;$0=$2.text;if(Aras.IOME.ItemCache.$7($0)){$p1[$0]=true;}}}
Aras.IOME.ItemCache.$5=function($p0,$p1){var $0=$p0.text;if(Aras.IOME.ItemCache.$7($0)){$p1[$0]=true;}}
Aras.IOME.ItemCache.$6=function($p0,$p1){var $enum1=ss.IEnumerator.getEnumerator($p0);while($enum1.moveNext()){var $0=$enum1.current;var $1=$0;if(Aras.IOME.ItemCache.$7($0)){$p1[$1]=true;}}}
Aras.IOME.ItemCache.$7=function($p0){var $0=Type.safeCast($p0,String);if($0!=null){return Aras.IOME.ItemCache.$2.test($0);}else{return false;}}
Aras.IOME.ItemCache.$9=function($p0,$p1){if(!Object.getKeyCount($p1)){return $p0;}var $0={};var $enum1=ss.IEnumerator.getEnumerator(Object.keys($p0));while($enum1.moveNext()){var $1=$enum1.current;var $2=$1;if(!Object.keyExists($p1,$2)){$0[$2]=$p0[$2];}}return $0;}
Aras.IOME.ItemCache.$C=function($p0){for(var $0=0;$0<$p0.length;$0++){var $1=$p0[$0];if(!((Type.canCast($1,String))||(Type.canCast($1,Boolean)))){Aras.IOME.ItemCache.$D('key',$1);}}}
Aras.IOME.ItemCache.$D=function($p0,$p1){var $0='NULL';if($p1!=null){$0=Type.getInstanceType($p1).get_fullName();}var $1=$0+' is an illegal datatype.';throw new Error($1+$p0);}
Aras.IOME.ItemCache.prototype={$0:null,$1:null,ClearCache:function(){this.clear();},RemoveById:function(id){return this.RemoveAllItems(id);},RemoveAllItems:function(itemId){return this.Remove([itemId]);},Remove:function(idlist){if(idlist==null||!idlist.length){return false;}var $0={};for(var $1=0;$1<idlist.length;$1++){var $2=idlist[$1];if(String.isNullOrEmpty($2)){continue;}var $3=this.$1[$2];if($3!=null){var $4=[];var $enum1=ss.IEnumerator.getEnumerator(Object.keys($3));while($enum1.moveNext()){var $5=$enum1.current;$4.add($5);}$0[$2]=$4;}}if(Object.getKeyCount($0)>0){var $enum2=ss.IEnumerator.getEnumerator(Object.keys($0));while($enum2.moveNext()){var $6=$enum2.current;delete this.$1[$6];var $7=$0[$6];for(var $8=0;$8<$7.length;$8++){this.removeFromHash($7[$8]);}}return true;}return false;},removeFromHash:function(skey){var $0=skey;var $1=[];var $2=$0.split(',');var $enum1=ss.IEnumerator.getEnumerator($2);while($enum1.moveNext()){var $5=$enum1.current;$1.add($5);}if($0==null){throw new Error('key');}var $3={};var $4=null;if(Object.keyExists(this.$0,$0)){$4=this.$0[$0];Aras.IOME.ItemCache.$3($4,$3);Aras.IOME.ItemCache.$6($1,$3);this.$B($3,$1);delete this.$0[$0];return true;}else{return false;}},GetItem:function(key){var $0=(key);return this.$0[$0];},SetItem:function(key,val){return this.$8(key,val);},$8:function($p0,$p1){var $0=($p0);Aras.IOME.ItemCache.$C($p0);var $1={};var $2={};var $3;var $4;var $5=null;Aras.IOME.ItemCache.$3($p1,$1);Aras.IOME.ItemCache.$6($p0,$1);if(Object.keyExists(this.$0,$0)){$5=this.$0[$0];if($5===$p1){$5=null;}else{Aras.IOME.ItemCache.$3($5,$2);Aras.IOME.ItemCache.$6($p0,$2);}}$3=Aras.IOME.ItemCache.$9($1,$2);$4=Aras.IOME.ItemCache.$9($2,$1);this.$A($3,$p0);this.$B($4,$p0);this.$0[$0]=$p1;if($5!=null){return true;}else{return false;}},$A:function($p0,$p1){var $0;var $enum1=ss.IEnumerator.getEnumerator(Object.keys($p0));while($enum1.moveNext()){var $1=$enum1.current;$0=this.$1[$1]||null;if($0==null){$0={};this.$1[$1]=$0;}var $2=($p1);$0[$2]=true;}},$B:function($p0,$p1){var $0;var $enum1=ss.IEnumerator.getEnumerator(Object.keys($p0));while($enum1.moveNext()){var $1=$enum1.current;var $2=($p1);$0=this.$1[$1];if($0!=null){delete $0[$2];}}},clear:function(){Object.clearKeys(this.$0);Object.clearKeys(this.$1);},keys:function(){return Object.keys(this.$0);},dependencies:function(){return Object.keys(this.$1);},describeKey:function(key){if(key==null){throw new Error('key');}var $0,$1,$2=0;var $3;$1=key.length;if(!$1){return '';}for($0=0;$0<$1;++$0){$3=key[$0].toString();$2=$2+$3.length;}var $4=new ss.StringBuilder();for($0=0;$0<$1;++$0){$4.append(key[$0]);if(($0+1)<$1){$4.append(':');}}return $4.toString();},withinlocker:function(fcn,arg){if(fcn==null){throw new Error('fcn');}var $0;$0=fcn(arg);return $0;},containsKey:function(key){var $0=(key);return Object.keyExists(this.$0,$0);},GetItemsById:function(id){var $0=this.$E(id);var $1=[];var $enum1=ss.IEnumerator.getEnumerator($0);while($enum1.moveNext()){var $2=$enum1.current;var $3=($2);if(Object.keyExists(this.$0,$3)){$1.add(this.$0[$3]);}}return $1;},$E:function($p0){var $0=[];if(!ss.isNullOrUndefined(this.$1[$p0])){$0.addRange(Object.keys((this.$1[$p0])));}return $0;},$F:function($p0){var $0=[];var $enum1=ss.IEnumerator.getEnumerator(Object.keys($p0));while($enum1.moveNext()){var $2=$enum1.current;$0.add($2);}var $1=new Aras.IOME._KeyComparator();$0.sort(ss.Delegate.create($1,$1.$1));return $0;}}
Type.registerNamespace('Aras.IOME.Licensing');Aras.IOME.Licensing.ILicenseManagerWebService=function(){};Aras.IOME.Licensing.ILicenseManagerWebService.registerInterface('Aras.IOME.Licensing.ILicenseManagerWebService');Aras.IOME.Licensing.IOMScriptSharp$2=function(){};Aras.IOME.Licensing.IOMScriptSharp$2.registerInterface('Aras.IOME.Licensing.IOMScriptSharp$2');Aras.IOME.Licensing.LicenseManager=function(serverConnection){if(serverConnection==null){throw new Error('serverConnection');}try{var $0=(serverConnection);this.$1=$0.getLicenseManagerWebService();}catch($1){throw new Error("Current implementation of Aras.IOM.IServerConnection doesn't implement Aras.IOM.ILicenseManagerWebServiceFactory");}}
Aras.IOME.Licensing.LicenseManager.prototype={$1:null,consumeLicense:function(featureName){if(String.isNullOrEmpty(featureName)){throw new Error('Feature name must be specified.');}return this.$1.consumeLicense(featureName);}}
Aras.IOME.Licensing.IOMScriptSharp$3=function(){this.$0=new LicenseManagerWebServiceClient();}
Aras.IOME.Licensing.IOMScriptSharp$3.prototype={$0:null,consumeLicense:function($p0){return this.$0.ConsumeLicense($p0);},releaseLicense:function($p0){throw new Error('NotImplementedException: ReleaseLicense not implemented');},getServerInfo:function(){throw new Error('NotImplementedException: GetServerInfo not implemented');},getFeatureTree:function(){throw new Error('NotImplementedException: GetFeatureTree not implemented');},updateFeatureTree:function($p0){throw new Error('NotImplementedException: UpdateFeatureTree not implemented');},importFeatureLicense:function($p0){throw new Error('NotImplementedException: ImportFeatureLicense not implemented');}}
Type.registerNamespace('Aras.IOM.Vault');Aras.IOM.Vault.IOMScriptSharp$4=function(id,vaultId,vaultUrl){this.id=id;this.$0=vaultId;this.$1=vaultUrl;}
Aras.IOM.Vault.IOMScriptSharp$4.prototype={$0:null,$1:null,id:null}
Type.registerNamespace('Aras.SoapConstants');Aras.SoapConstants._Soap=function(){}
Aras.IOM.InnovatorUser=function(){}
Aras.IOM.InnovatorUser.get_Current=function(){return Aras.IOM.InnovatorUser.$0||(Aras.IOM.InnovatorUser.$0=new Aras.IOM.InnovatorUser());}
Aras.IOM.InnovatorUser.prototype={Init:function(userName,password,dbName,connection,context){this.UserName=userName;this.Password=password;this.DatabaseName=dbName;this.ISConnection=connection;this.SessionContext=context;},UserName:null,Password:null,DatabaseName:null,ISConnection:null,SessionContext:null}
StringComparison.registerClass('StringComparison');CompressionType.registerClass('CompressionType');RegexOptions.registerClass('RegexOptions');HttpUtility.registerClass('HttpUtility');Aras.IOM.HttpConnectionParameters.registerClass('Aras.IOM.HttpConnectionParameters');Aras.IOM.I18NSessionContext.registerClass('Aras.IOM.I18NSessionContext');Aras.IOM.IOMScriptSharp$5.registerClass('Aras.IOM.IOMScriptSharp$5');Aras.IOM.InternalUtils.registerClass('Aras.IOM.InternalUtils');Aras.IOM.XmlExtension.registerClass('Aras.IOM.XmlExtension');Aras.IOM.IomFactory.registerClass('Aras.IOM.IomFactory');Aras.IOM.ServerConnectionBase.registerClass('Aras.IOM.ServerConnectionBase',null,Aras.IOM.IServerConnection);Aras.IOM.HttpServerConnection.registerClass('Aras.IOM.HttpServerConnection',Aras.IOM.ServerConnectionBase);Aras.IOM.Innovator.registerClass('Aras.IOM.Innovator');Aras.IOM.Item.registerClass('Aras.IOM.Item');Aras.IOM.InnovatorServerConnector.registerClass('Aras.IOM.InnovatorServerConnector',Aras.IOM.ServerConnectionBase,Aras.IOME.Licensing.IOMScriptSharp$2);Aras.IOM.IOMScriptSharp$6.registerClass('Aras.IOM.IOMScriptSharp$6',Aras.IOM.HttpServerConnection);Aras.IOM.WinAuthHttpServerConnection.registerClass('Aras.IOM.WinAuthHttpServerConnection',Aras.IOM.HttpServerConnection);Aras.Utils.HeaderClientData.registerClass('Aras.Utils.HeaderClientData',null,Aras.Utils.IClientData);Aras.I18NUtils.Intl.registerClass('Aras.I18NUtils.Intl');Aras.I18NUtils.ArasNumber.registerClass('Aras.I18NUtils.ArasNumber');Aras.I18NUtils._I18NConverter.registerClass('Aras.I18NUtils._I18NConverter');Aras.I18NUtils.I18NSystemInfo.registerClass('Aras.I18NUtils.I18NSystemInfo');Aras.IOME.CacheableContainer.registerClass('Aras.IOME.CacheableContainer',null,Aras.IOME.ICacheable);Aras.IOME._KeyComparator.registerClass('Aras.IOME._KeyComparator');Aras.IOME.ArrayListComparer.registerClass('Aras.IOME.ArrayListComparer');Aras.IOME.ItemCache.registerClass('Aras.IOME.ItemCache');Aras.IOME.Licensing.LicenseManager.registerClass('Aras.IOME.Licensing.LicenseManager');Aras.IOME.Licensing.IOMScriptSharp$3.registerClass('Aras.IOME.Licensing.IOMScriptSharp$3',null,Aras.IOME.Licensing.ILicenseManagerWebService);Aras.IOM.Vault.IOMScriptSharp$4.registerClass('Aras.IOM.Vault.IOMScriptSharp$4');Aras.SoapConstants._Soap.registerClass('Aras.SoapConstants._Soap');Aras.IOM.InnovatorUser.registerClass('Aras.IOM.InnovatorUser');StringComparison.ordinalIgnoreCase=false;CompressionType.deflate='deflate';CompressionType.gzip='gzip';CompressionType.none='none';RegexOptions.compiled='';RegexOptions.cultureInvariant='';RegexOptions.ecmaScript='';RegexOptions.explicitCapture='';RegexOptions.ignoreCase='i';RegexOptions.ignorePatternWhitespace='';RegexOptions.multiline='';RegexOptions.none='';RegexOptions.rightToLeft='';RegexOptions.singleline='';Aras.IOM.HttpServerConnection.$13=Aras.SoapConstants._Soap.$6+'<'+'SOAP-ENV'+':Fault>\r\n\t<faultcode>999</faultcode>\r\n\t<faultstring>HTTP Error</faultstring>\r\n\t<faultactor>HttpServerConnection</faultactor>\r\n\t<detail>unknown error</detail>\r\n</'+'SOAP-ENV'+':Fault>'+Aras.SoapConstants._Soap.$7;Aras.IOM.HttpServerConnection.$19=new RegExp('^([0-9A-F]{32})|([0-9A-F]{64})$',RegexOptions.compiled+RegexOptions.ignoreCase);Aras.IOM.Item.xPathResult='//Result';Aras.IOM.Item.xPathResultItem=Aras.IOM.Item.xPathResult+'/Item';Aras.IOM.Item.xPathFault="/*[local-name()='Envelope' and (namespace-uri()='http://schemas.xmlsoap.org/soap/envelope/' or namespace-uri()='')]/*[local-name()='Body' and (namespace-uri()='http://schemas.xmlsoap.org/soap/envelope/' or namespace-uri()='')]/*[local-name()='Fault' and (namespace-uri()='http://schemas.xmlsoap.org/soap/envelope/' or namespace-uri()='')]";Aras.IOM.Item.$2="WorkflowMap ID is either 'null' or empty string";Aras.IOM.Item.$3='The item is a new item';Aras.IOM.Item.$4='instantiateWorkflow';Aras.IOM.Item.$6="Wrong internal structure of the {0}; e.g. item's \"dom\" is not set; or item's \"node\" doesn't "+"belong to the item's \"dom\"; or both \"node\" and \"nodeList\" are null; etc.";Aras.IOM.InnovatorServerConnector.$F=new RegExp('^[0-9A-F]{32}$',RegexOptions.ignoreCase);Aras.I18NUtils._I18NConverter.$0='yyyy-MM-ddTHH:mm:ss';Aras.I18NUtils._I18NConverter.$1='yyyy-MM-dd';Aras.I18NUtils._I18NConverter.$2=null;Aras.I18NUtils._I18NConverter.$5={};Aras.IOME.ItemCache.$2=new RegExp('^[0-9A-F]{32}$',RegexOptions.compiled);Aras.SoapConstants._Soap.$6='<'+'SOAP-ENV'+':Envelope xmlns:'+'SOAP-ENV'+'="'+'http://schemas.xmlsoap.org/soap/envelope/'+'" xmlns:'+'i18n'+'="'+'http://www.aras.com/I18N'+'"><'+'SOAP-ENV'+':Body>';Aras.SoapConstants._Soap.$7='</'+'SOAP-ENV'+':Body></'+'SOAP-ENV'+':Envelope>';Aras.SoapConstants._Soap.$8="namespace-uri()='"+'http://schemas.xmlsoap.org/soap/envelope/'+"' or namespace-uri()=''";Aras.SoapConstants._Soap.$9="*[local-name()='Envelope' and ("+Aras.SoapConstants._Soap.$8+')]';Aras.SoapConstants._Soap.$A="*[local-name()='Body' and ("+Aras.SoapConstants._Soap.$8+')]';Aras.SoapConstants._Soap.$B="*[local-name()='Result' and ("+Aras.SoapConstants._Soap.$8+')]';Aras.SoapConstants._Soap.$C="*[local-name()='Fault' and ("+Aras.SoapConstants._Soap.$8+')]';Aras.SoapConstants._Soap.$D=Aras.SoapConstants._Soap.$9+'/'+Aras.SoapConstants._Soap.$A;Aras.SoapConstants._Soap.$E=Aras.SoapConstants._Soap.$D+'/'+Aras.SoapConstants._Soap.$B;Aras.SoapConstants._Soap.$F=Aras.SoapConstants._Soap.$D+'/'+Aras.SoapConstants._Soap.$C;Aras.IOM.InnovatorUser.$0=null;})();// This script was generated using Script# v0.7.4.0


/** ..\Modules\polyfills\resizeObserver.min.js **/
!function(t,e){"object"==typeof exports&&"undefined"!=typeof module?module.exports=e():t.ResizeObserver=e()}(this,function(){"use strict";function t(t){return parseFloat(t)||0}function e(e){for(var n=[],r=arguments.length-1;r-- >0;)n[r]=arguments[r+1];return n.reduce(function(n,r){return n+t(e["border-"+r+"-width"])},0)}function n(e){for(var n={},r=0,i=["top","right","bottom","left"];r<i.length;r+=1){var o=i[r],s=e["padding-"+o];n[o]=t(s)}return n}function r(t){var e=t.getBBox();return a(0,0,e.width,e.height)}function i(r){var i=r.clientWidth,s=r.clientHeight;if(!i&&!s)return w;var c=g(r).getComputedStyle(r),h=n(c),u=h.left+h.right,f=h.top+h.bottom,d=t(c.width),p=t(c.height);if("border-box"===c.boxSizing&&(Math.round(d+u)!==i&&(d-=e(c,"left","right")+u),Math.round(p+f)!==s&&(p-=e(c,"top","bottom")+f)),!o(r)){var v=Math.round(d+u)-i,l=Math.round(p+f)-s;1!==Math.abs(v)&&(d-=v),1!==Math.abs(l)&&(p-=l)}return a(h.left,h.top,d,p)}function o(t){return t===g(t).document.documentElement}function s(t){return u?O(t)?r(t):i(t):w}function c(t){var e=t.x,n=t.y,r=t.width,i=t.height,o="undefined"!=typeof DOMRectReadOnly?DOMRectReadOnly:Object,s=Object.create(o.prototype);return y(s,{x:e,y:n,width:r,height:i,top:n,right:e+r,bottom:i+n,left:e}),s}function a(t,e,n,r){return{x:t,y:e,width:n,height:r}}var h=function(){function t(t,e){var n=-1;return t.some(function(t,r){return t[0]===e&&(n=r,!0)}),n}return"undefined"!=typeof Map?Map:function(){function e(){this.__entries__=[]}var n={size:{configurable:!0}};return n.size.get=function(){return this.__entries__.length},e.prototype.get=function(e){var n=t(this.__entries__,e),r=this.__entries__[n];return r&&r[1]},e.prototype.set=function(e,n){var r=t(this.__entries__,e);~r?this.__entries__[r][1]=n:this.__entries__.push([e,n])},e.prototype.delete=function(e){var n=this.__entries__,r=t(n,e);~r&&n.splice(r,1)},e.prototype.has=function(e){return!!~t(this.__entries__,e)},e.prototype.clear=function(){this.__entries__.splice(0)},e.prototype.forEach=function(t,e){void 0===e&&(e=null);for(var n=0,r=this.__entries__;n<r.length;n+=1){var i=r[n];t.call(e,i[1],i[0])}},Object.defineProperties(e.prototype,n),e}()}(),u="undefined"!=typeof window&&"undefined"!=typeof document&&window.document===document,f="undefined"!=typeof global&&global.Math===Math?global:"undefined"!=typeof self&&self.Math===Math?self:"undefined"!=typeof window&&window.Math===Math?window:Function("return this")(),d="function"==typeof requestAnimationFrame?requestAnimationFrame.bind(f):function(t){return setTimeout(function(){return t(Date.now())},1e3/60)},p=2,v=function(t,e){function n(){o&&(o=!1,t()),s&&i()}function r(){d(n)}function i(){var t=Date.now();if(o){if(t-c<p)return;s=!0}else o=!0,s=!1,setTimeout(r,e);c=t}var o=!1,s=!1,c=0;return i},l=20,_=["top","right","bottom","left","width","height","size","weight"],b="undefined"!=typeof MutationObserver,m=function(){this.connected_=!1,this.mutationEventsAdded_=!1,this.mutationsObserver_=null,this.observers_=[],this.onTransitionEnd_=this.onTransitionEnd_.bind(this),this.refresh=v(this.refresh.bind(this),l)};m.prototype.addObserver=function(t){~this.observers_.indexOf(t)||this.observers_.push(t),this.connected_||this.connect_()},m.prototype.removeObserver=function(t){var e=this.observers_,n=e.indexOf(t);~n&&e.splice(n,1),!e.length&&this.connected_&&this.disconnect_()},m.prototype.refresh=function(){this.updateObservers_()&&this.refresh()},m.prototype.updateObservers_=function(){var t=this.observers_.filter(function(t){return t.gatherActive(),t.hasActive()});return t.forEach(function(t){return t.broadcastActive()}),t.length>0},m.prototype.connect_=function(){u&&!this.connected_&&(document.addEventListener("transitionend",this.onTransitionEnd_),window.addEventListener("resize",this.refresh),b?(this.mutationsObserver_=new MutationObserver(this.refresh),this.mutationsObserver_.observe(document,{attributes:!0,childList:!0,characterData:!0,subtree:!0})):(document.addEventListener("DOMSubtreeModified",this.refresh),this.mutationEventsAdded_=!0),this.connected_=!0)},m.prototype.disconnect_=function(){u&&this.connected_&&(document.removeEventListener("transitionend",this.onTransitionEnd_),window.removeEventListener("resize",this.refresh),this.mutationsObserver_&&this.mutationsObserver_.disconnect(),this.mutationEventsAdded_&&document.removeEventListener("DOMSubtreeModified",this.refresh),this.mutationsObserver_=null,this.mutationEventsAdded_=!1,this.connected_=!1)},m.prototype.onTransitionEnd_=function(t){var e=t.propertyName;void 0===e&&(e="");_.some(function(t){return!!~e.indexOf(t)})&&this.refresh()},m.getInstance=function(){return this.instance_||(this.instance_=new m),this.instance_},m.instance_=null;var y=function(t,e){for(var n=0,r=Object.keys(e);n<r.length;n+=1){var i=r[n];Object.defineProperty(t,i,{value:e[i],enumerable:!1,writable:!1,configurable:!0})}return t},g=function(t){return t&&t.ownerDocument&&t.ownerDocument.defaultView||f},w=a(0,0,0,0),O="undefined"!=typeof SVGGraphicsElement?function(t){return t instanceof g(t).SVGGraphicsElement}:function(t){return t instanceof g(t).SVGElement&&"function"==typeof t.getBBox},E=function(t){this.broadcastWidth=0,this.broadcastHeight=0,this.contentRect_=a(0,0,0,0),this.target=t};E.prototype.isActive=function(){var t=s(this.target);return this.contentRect_=t,t.width!==this.broadcastWidth||t.height!==this.broadcastHeight},E.prototype.broadcastRect=function(){var t=this.contentRect_;return this.broadcastWidth=t.width,this.broadcastHeight=t.height,t};var M=function(t,e){var n=c(e);y(this,{target:t,contentRect:n})},A=function(t,e,n){if(this.activeObservations_=[],this.observations_=new h,"function"!=typeof t)throw new TypeError("The callback provided as parameter 1 is not a function.");this.callback_=t,this.controller_=e,this.callbackCtx_=n};A.prototype.observe=function(t){if(!arguments.length)throw new TypeError("1 argument required, but only 0 present.");if("undefined"!=typeof Element&&Element instanceof Object){if(!(t instanceof g(t).Element))throw new TypeError('parameter 1 is not of type "Element".');var e=this.observations_;e.has(t)||(e.set(t,new E(t)),this.controller_.addObserver(this),this.controller_.refresh())}},A.prototype.unobserve=function(t){if(!arguments.length)throw new TypeError("1 argument required, but only 0 present.");if("undefined"!=typeof Element&&Element instanceof Object){if(!(t instanceof g(t).Element))throw new TypeError('parameter 1 is not of type "Element".');var e=this.observations_;e.has(t)&&(e.delete(t),e.size||this.controller_.removeObserver(this))}},A.prototype.disconnect=function(){this.clearActive(),this.observations_.clear(),this.controller_.removeObserver(this)},A.prototype.gatherActive=function(){var t=this;this.clearActive(),this.observations_.forEach(function(e){e.isActive()&&t.activeObservations_.push(e)})},A.prototype.broadcastActive=function(){if(this.hasActive()){var t=this.callbackCtx_,e=this.activeObservations_.map(function(t){return new M(t.target,t.broadcastRect())});this.callback_.call(t,e,t),this.clearActive()}},A.prototype.clearActive=function(){this.activeObservations_.splice(0)},A.prototype.hasActive=function(){return this.activeObservations_.length>0};var T="undefined"!=typeof WeakMap?new WeakMap:new h,x=function(t){if(!(this instanceof x))throw new TypeError("Cannot call a class as a function.");if(!arguments.length)throw new TypeError("1 argument required, but only 0 present.");var e=m.getInstance(),n=new A(t,e,this);T.set(this,n)};["observe","unobserve","disconnect"].forEach(function(t){x.prototype[t]=function(){return(e=T.get(this))[t].apply(e,arguments);var e}});return void 0!==f.ResizeObserver?f.ResizeObserver:x});

/** ..\Modules\cryptohash\cryptoJS.js **/
 /*
     CryptoJS v3.1.2
     code.google.com/p/crypto-js
     (c) 2009-2013 by Jeff Mott. All rights reserved.
     code.google.com/p/crypto-js/wiki/License
     */
    /**
     * CryptoJS core components.
     */
    CryptoJS = (function (Math, undefined) {
            /**
             * CryptoJS namespace.
             */
            var C = {};

            /**
             * Library namespace.
             */
            var C_lib = C.lib = {};

            /**
             * Base object for prototypal inheritance.
             */
            var Base = C_lib.Base = (function () {
                function F() {}

                return {
                    /**
                     * Creates a new object that inherits from this object.
                     *
                     * @param {Object} overrides Properties to copy into the new object.
                     *
                     * @return {Object} The new object.
                     *
                     * @static
                     *
                     * @example
                     *
                     *     var MyType = CryptoJS.lib.Base.extend({
         *         field: 'value',
         *
         *         method: function () {
         *         }
         *     });
                     */
                    extend: function (overrides) {
                        // Spawn
                        F.prototype = this;
                        var subtype = new F();

                        // Augment
                        if (overrides) {
                            subtype.mixIn(overrides);
                        }

                        // Create default initializer
                        if (!subtype.hasOwnProperty('init')) {
                            subtype.init = function () {
                                subtype.$super.init.apply(this, arguments);
                            };
                        }

                        // Initializer's prototype is the subtype object
                        subtype.init.prototype = subtype;

                        // Reference supertype
                        subtype.$super = this;

                        return subtype;
                    },

                    /**
                     * Extends this object and runs the init method.
                     * Arguments to create() will be passed to init().
                     *
                     * @return {Object} The new object.
                     *
                     * @static
                     *
                     * @example
                     *
                     *     var instance = MyType.create();
                     */
                    create: function () {
                        var instance = this.extend();
                        instance.init.apply(instance, arguments);

                        return instance;
                    },

                    /**
                     * Initializes a newly created object.
                     * Override this method to add some logic when your objects are created.
                     *
                     * @example
                     *
                     *     var MyType = CryptoJS.lib.Base.extend({
         *         init: function () {
         *             // ...
         *         }
         *     });
                     */
                    init: function () {
                    },

                    /**
                     * Copies properties into this object.
                     *
                     * @param {Object} properties The properties to mix in.
                     *
                     * @example
                     *
                     *     MyType.mixIn({
         *         field: 'value'
         *     });
                     */
                    mixIn: function (properties) {
                        for (var propertyName in properties) {
                            if (properties.hasOwnProperty(propertyName)) {
                                this[propertyName] = properties[propertyName];
                            }
                        }

                        // IE won't copy toString using the loop above
                        if (properties.hasOwnProperty('toString')) {
                            this.toString = properties.toString;
                        }
                    },

                    /**
                     * Creates a copy of this object.
                     *
                     * @return {Object} The clone.
                     *
                     * @example
                     *
                     *     var clone = instance.clone();
                     */
                    clone: function () {
                        return this.init.prototype.extend(this);
                    }
                };
            }());

            /**
             * An array of 32-bit words.
             *
             * @property {Array} words The array of 32-bit words.
             * @property {number} sigBytes The number of significant bytes in this word array.
             */
            var WordArray = C_lib.WordArray = Base.extend({
                /**
                 * Initializes a newly created word array.
                 *
                 * @param {Array} words (Optional) An array of 32-bit words.
                 * @param {number} sigBytes (Optional) The number of significant bytes in the words.
                 *
                 * @example
                 *
                 *     var wordArray = CryptoJS.lib.WordArray.create();
                 *     var wordArray = CryptoJS.lib.WordArray.create([0x00010203, 0x04050607]);
                 *     var wordArray = CryptoJS.lib.WordArray.create([0x00010203, 0x04050607], 6);
                 */
                init: function (words, sigBytes) {
                    words = this.words = words || [];

                    if (sigBytes != undefined) {
                        this.sigBytes = sigBytes;
                    } else {
                        this.sigBytes = words.length * 4;
                    }
                },

                /**
                 * Converts this word array to a string.
                 *
                 * @param {Encoder} encoder (Optional) The encoding strategy to use. Default: CryptoJS.enc.Hex
                 *
                 * @return {string} The stringified word array.
                 *
                 * @example
                 *
                 *     var string = wordArray + '';
                 *     var string = wordArray.toString();
                 *     var string = wordArray.toString(CryptoJS.enc.Utf8);
                 */
                toString: function (encoder) {
                    return (encoder || Hex).stringify(this);
                },

                /**
                 * Concatenates a word array to this word array.
                 *
                 * @param {WordArray} wordArray The word array to append.
                 *
                 * @return {WordArray} This word array.
                 *
                 * @example
                 *
                 *     wordArray1.concat(wordArray2);
                 */
                concat: function (wordArray) {
                    // Shortcuts
                    var thisWords = this.words;
                    var thatWords = wordArray.words;
                    var thisSigBytes = this.sigBytes;
                    var thatSigBytes = wordArray.sigBytes;

                    // Clamp excess bits
                    this.clamp();

                    // Concat
                    if (thisSigBytes % 4) {
                        // Copy one byte at a time
                        for (var i = 0; i < thatSigBytes; i++) {
                            var thatByte = (thatWords[i >>> 2] >>> (24 - (i % 4) * 8)) & 0xff;
                            thisWords[(thisSigBytes + i) >>> 2] |= thatByte << (24 - ((thisSigBytes + i) % 4) * 8);
                        }
                    } else if (thatWords.length > 0xffff) {
                        // Copy one word at a time
                        for (var i = 0; i < thatSigBytes; i += 4) {
                            thisWords[(thisSigBytes + i) >>> 2] = thatWords[i >>> 2];
                        }
                    } else {
                        // Copy all words at once
                        thisWords.push.apply(thisWords, thatWords);
                    }
                    this.sigBytes += thatSigBytes;

                    // Chainable
                    return this;
                },

                /**
                 * Removes insignificant bits.
                 *
                 * @example
                 *
                 *     wordArray.clamp();
                 */
                clamp: function () {
                    // Shortcuts
                    var words = this.words;
                    var sigBytes = this.sigBytes;

                    // Clamp
                    words[sigBytes >>> 2] &= 0xffffffff << (32 - (sigBytes % 4) * 8);
                    words.length = Math.ceil(sigBytes / 4);
                },

                /**
                 * Creates a copy of this word array.
                 *
                 * @return {WordArray} The clone.
                 *
                 * @example
                 *
                 *     var clone = wordArray.clone();
                 */
                clone: function () {
                    var clone = Base.clone.call(this);
                    clone.words = this.words.slice(0);

                    return clone;
                },

                /**
                 * Creates a word array filled with random bytes.
                 *
                 * @param {number} nBytes The number of random bytes to generate.
                 *
                 * @return {WordArray} The random word array.
                 *
                 * @static
                 *
                 * @example
                 *
                 *     var wordArray = CryptoJS.lib.WordArray.random(16);
                 */
                random: function (nBytes) {
                    var words = [];
                    for (var i = 0; i < nBytes; i += 4) {
                        words.push((Math.random() * 0x100000000) | 0);
                    }

                    return new WordArray.init(words, nBytes);
                }
            });

            /**
             * Encoder namespace.
             */
            var C_enc = C.enc = {};

            /**
             * Hex encoding strategy.
             */
            var Hex = C_enc.Hex = {
                /**
                 * Converts a word array to a hex string.
                 *
                 * @param {WordArray} wordArray The word array.
                 *
                 * @return {string} The hex string.
                 *
                 * @static
                 *
                 * @example
                 *
                 *     var hexString = CryptoJS.enc.Hex.stringify(wordArray);
                 */
                stringify: function (wordArray) {
                    // Shortcuts
                    var words = wordArray.words;
                    var sigBytes = wordArray.sigBytes;

                    // Convert
                    var hexChars = [];
                    for (var i = 0; i < sigBytes; i++) {
                        var bite = (words[i >>> 2] >>> (24 - (i % 4) * 8)) & 0xff;
                        hexChars.push((bite >>> 4).toString(16));
                        hexChars.push((bite & 0x0f).toString(16));
                    }

                    return hexChars.join('');
                },

                /**
                 * Converts a hex string to a word array.
                 *
                 * @param {string} hexStr The hex string.
                 *
                 * @return {WordArray} The word array.
                 *
                 * @static
                 *
                 * @example
                 *
                 *     var wordArray = CryptoJS.enc.Hex.parse(hexString);
                 */
                parse: function (hexStr) {
                    // Shortcut
                    var hexStrLength = hexStr.length;

                    // Convert
                    var words = [];
                    for (var i = 0; i < hexStrLength; i += 2) {
                        words[i >>> 3] |= parseInt(hexStr.substr(i, 2), 16) << (24 - (i % 8) * 4);
                    }

                    return new WordArray.init(words, hexStrLength / 2);
                }
            };

            /**
             * Latin1 encoding strategy.
             */
            var Latin1 = C_enc.Latin1 = {
                /**
                 * Converts a word array to a Latin1 string.
                 *
                 * @param {WordArray} wordArray The word array.
                 *
                 * @return {string} The Latin1 string.
                 *
                 * @static
                 *
                 * @example
                 *
                 *     var latin1String = CryptoJS.enc.Latin1.stringify(wordArray);
                 */
                stringify: function (wordArray) {
                    // Shortcuts
                    var words = wordArray.words;
                    var sigBytes = wordArray.sigBytes;

                    // Convert
                    var latin1Chars = [];
                    for (var i = 0; i < sigBytes; i++) {
                        var bite = (words[i >>> 2] >>> (24 - (i % 4) * 8)) & 0xff;
                        latin1Chars.push(String.fromCharCode(bite));
                    }

                    return latin1Chars.join('');
                },

                /**
                 * Converts a Latin1 string to a word array.
                 *
                 * @param {string} latin1Str The Latin1 string.
                 *
                 * @return {WordArray} The word array.
                 *
                 * @static
                 *
                 * @example
                 *
                 *     var wordArray = CryptoJS.enc.Latin1.parse(latin1String);
                 */
                parse: function (latin1Str) {
                    // Shortcut
                    var latin1StrLength = latin1Str.length;

                    // Convert
                    var words = [];
                    for (var i = 0; i < latin1StrLength; i++) {
                        words[i >>> 2] |= (latin1Str.charCodeAt(i) & 0xff) << (24 - (i % 4) * 8);
                    }

                    return new WordArray.init(words, latin1StrLength);
                }
            };

            /**
             * UTF-8 encoding strategy.
             */
            var Utf8 = C_enc.Utf8 = {
                /**
                 * Converts a word array to a UTF-8 string.
                 *
                 * @param {WordArray} wordArray The word array.
                 *
                 * @return {string} The UTF-8 string.
                 *
                 * @static
                 *
                 * @example
                 *
                 *     var utf8String = CryptoJS.enc.Utf8.stringify(wordArray);
                 */
                stringify: function (wordArray) {
                    try {
                        return decodeURIComponent(escape(Latin1.stringify(wordArray)));
                    } catch (e) {
                        throw new Error('Malformed UTF-8 data');
                    }
                },

                /**
                 * Converts a UTF-8 string to a word array.
                 *
                 * @param {string} utf8Str The UTF-8 string.
                 *
                 * @return {WordArray} The word array.
                 *
                 * @static
                 *
                 * @example
                 *
                 *     var wordArray = CryptoJS.enc.Utf8.parse(utf8String);
                 */
                parse: function (utf8Str) {
                    return Latin1.parse(unescape(encodeURIComponent(utf8Str)));
                }
            };

            /**
             * Abstract buffered block algorithm template.
             *
             * The property blockSize must be implemented in a concrete subtype.
             *
             * @property {number} _minBufferSize The number of blocks that should be kept unprocessed in the buffer. Default: 0
             */
            var BufferedBlockAlgorithm = C_lib.BufferedBlockAlgorithm = Base.extend({
                /**
                 * Resets this block algorithm's data buffer to its initial state.
                 *
                 * @example
                 *
                 *     bufferedBlockAlgorithm.reset();
                 */
                reset: function () {
                    // Initial values
                    this._data = new WordArray.init();
                    this._nDataBytes = 0;
                },

                /**
                 * Adds new data to this block algorithm's buffer.
                 *
                 * @param {WordArray|string} data The data to append. Strings are converted to a WordArray using UTF-8.
                 *
                 * @example
                 *
                 *     bufferedBlockAlgorithm._append('data');
                 *     bufferedBlockAlgorithm._append(wordArray);
                 */
                _append: function (data) {
                    // Convert string to WordArray, else assume WordArray already
                    if (typeof data == 'string') {
                        data = Utf8.parse(data);
                    }

                    // Append
                    this._data.concat(data);
                    this._nDataBytes += data.sigBytes;
                },

                /**
                 * Processes available data blocks.
                 *
                 * This method invokes _doProcessBlock(offset), which must be implemented by a concrete subtype.
                 *
                 * @param {boolean} doFlush Whether all blocks and partial blocks should be processed.
                 *
                 * @return {WordArray} The processed data.
                 *
                 * @example
                 *
                 *     var processedData = bufferedBlockAlgorithm._process();
                 *     var processedData = bufferedBlockAlgorithm._process(!!'flush');
                 */
                _process: function (doFlush) {
                    // Shortcuts
                    var data = this._data;
                    var dataWords = data.words;
                    var dataSigBytes = data.sigBytes;
                    var blockSize = this.blockSize;
                    var blockSizeBytes = blockSize * 4;

                    // Count blocks ready
                    var nBlocksReady = dataSigBytes / blockSizeBytes;
                    if (doFlush) {
                        // Round up to include partial blocks
                        nBlocksReady = Math.ceil(nBlocksReady);
                    } else {
                        // Round down to include only full blocks,
                        // less the number of blocks that must remain in the buffer
                        nBlocksReady = Math.max((nBlocksReady | 0) - this._minBufferSize, 0);
                    }

                    // Count words ready
                    var nWordsReady = nBlocksReady * blockSize;

                    // Count bytes ready
                    var nBytesReady = Math.min(nWordsReady * 4, dataSigBytes);

                    // Process blocks
                    if (nWordsReady) {
                        for (var offset = 0; offset < nWordsReady; offset += blockSize) {
                            // Perform concrete-algorithm logic
                            this._doProcessBlock(dataWords, offset);
                        }

                        // Remove processed words
                        var processedWords = dataWords.splice(0, nWordsReady);
                        data.sigBytes -= nBytesReady;
                    }

                    // Return processed words
                    return new WordArray.init(processedWords, nBytesReady);
                },

                /**
                 * Creates a copy of this object.
                 *
                 * @return {Object} The clone.
                 *
                 * @example
                 *
                 *     var clone = bufferedBlockAlgorithm.clone();
                 */
                clone: function () {
                    var clone = Base.clone.call(this);
                    clone._data = this._data.clone();

                    return clone;
                },

                _minBufferSize: 0
            });

            /**
             * Abstract hasher template.
             *
             * @property {number} blockSize The number of 32-bit words this hasher operates on. Default: 16 (512 bits)
             */
            var Hasher = C_lib.Hasher = BufferedBlockAlgorithm.extend({
                /**
                 * Configuration options.
                 */
                cfg: Base.extend(),

                /**
                 * Initializes a newly created hasher.
                 *
                 * @param {Object} cfg (Optional) The configuration options to use for this hash computation.
                 *
                 * @example
                 *
                 *     var hasher = CryptoJS.algo.SHA256.create();
                 */
                init: function (cfg) {
                    // Apply config defaults
                    this.cfg = this.cfg.extend(cfg);

                    // Set initial values
                    this.reset();
                },

                /**
                 * Resets this hasher to its initial state.
                 *
                 * @example
                 *
                 *     hasher.reset();
                 */
                reset: function () {
                    // Reset data buffer
                    BufferedBlockAlgorithm.reset.call(this);

                    // Perform concrete-hasher logic
                    this._doReset();
                },

                /**
                 * Updates this hasher with a message.
                 *
                 * @param {WordArray|string} messageUpdate The message to append.
                 *
                 * @return {Hasher} This hasher.
                 *
                 * @example
                 *
                 *     hasher.update('message');
                 *     hasher.update(wordArray);
                 */
                update: function (messageUpdate) {
                    // Append
                    this._append(messageUpdate);

                    // Update the hash
                    this._process();

                    // Chainable
                    return this;
                },

                /**
                 * Finalizes the hash computation.
                 * Note that the finalize operation is effectively a destructive, read-once operation.
                 *
                 * @param {WordArray|string} messageUpdate (Optional) A final message update.
                 *
                 * @return {WordArray} The hash.
                 *
                 * @example
                 *
                 *     var hash = hasher.finalize();
                 *     var hash = hasher.finalize('message');
                 *     var hash = hasher.finalize(wordArray);
                 */
                finalize: function (messageUpdate) {
                    // Final message update
                    if (messageUpdate) {
                        this._append(messageUpdate);
                    }

                    // Perform concrete-hasher logic
                    var hash = this._doFinalize();

                    return hash;
                },

                blockSize: 512/32,

                /**
                 * Creates a shortcut function to a hasher's object interface.
                 *
                 * @param {Hasher} hasher The hasher to create a helper for.
                 *
                 * @return {Function} The shortcut function.
                 *
                 * @static
                 *
                 * @example
                 *
                 *     var SHA256 = CryptoJS.lib.Hasher._createHelper(CryptoJS.algo.SHA256);
                 */
                _createHelper: function (hasher) {
                    return function (message, cfg) {
                        return new hasher.init(cfg).finalize(message);
                    };
                },

                /**
                 * Creates a shortcut function to the HMAC's object interface.
                 *
                 * @param {Hasher} hasher The hasher to use in this HMAC helper.
                 *
                 * @return {Function} The shortcut function.
                 *
                 * @static
                 *
                 * @example
                 *
                 *     var HmacSHA256 = CryptoJS.lib.Hasher._createHmacHelper(CryptoJS.algo.SHA256);
                 */
                _createHmacHelper: function (hasher) {
                    return function (message, key) {
                        return new C_algo.HMAC.init(hasher, key).finalize(message);
                    };
                }
            });

            /**
             * Algorithm namespace.
             */
            var C_algo = C.algo = {};

            return C;
        }(Math));
/** ..\Modules\cryptohash\sha256.js **/
/*
CryptoJS v3.1.2
code.google.com/p/crypto-js
(c) 2009-2013 by Jeff Mott. All rights reserved.
code.google.com/p/crypto-js/wiki/License
*/
(function (Math) {
    // Shortcuts
    var C = CryptoJS;
    var C_lib = C.lib;
    var WordArray = C_lib.WordArray;
    var Hasher = C_lib.Hasher;
    var C_algo = C.algo;

    // Initialization and round constants tables
    var H = [];
    var K = [];

    // Compute constants
    (function () {
        function isPrime(n) {
            var sqrtN = Math.sqrt(n);
            for (var factor = 2; factor <= sqrtN; factor++) {
                if (!(n % factor)) {
                    return false;
                }
            }

            return true;
        }

        function getFractionalBits(n) {
            return ((n - (n | 0)) * 0x100000000) | 0;
        }

        var n = 2;
        var nPrime = 0;
        while (nPrime < 64) {
            if (isPrime(n)) {
                if (nPrime < 8) {
                    H[nPrime] = getFractionalBits(Math.pow(n, 1 / 2));
                }
                K[nPrime] = getFractionalBits(Math.pow(n, 1 / 3));

                nPrime++;
            }

            n++;
        }
    }());

    // Reusable object
    var W = [];

    /**
     * SHA-256 hash algorithm.
     */
    var SHA256 = C_algo.SHA256 = Hasher.extend({
        _doReset: function () {
            this._hash = new WordArray.init(H.slice(0));
        },

        _doProcessBlock: function (M, offset) {
            // Shortcut
            var H = this._hash.words;

            // Working variables
            var a = H[0];
            var b = H[1];
            var c = H[2];
            var d = H[3];
            var e = H[4];
            var f = H[5];
            var g = H[6];
            var h = H[7];

            // Computation
            for (var i = 0; i < 64; i++) {
                if (i < 16) {
                    W[i] = M[offset + i] | 0;
                } else {
                    var gamma0x = W[i - 15];
                    var gamma0  = ((gamma0x << 25) | (gamma0x >>> 7))  ^
                                  ((gamma0x << 14) | (gamma0x >>> 18)) ^
                                   (gamma0x >>> 3);

                    var gamma1x = W[i - 2];
                    var gamma1  = ((gamma1x << 15) | (gamma1x >>> 17)) ^
                                  ((gamma1x << 13) | (gamma1x >>> 19)) ^
                                   (gamma1x >>> 10);

                    W[i] = gamma0 + W[i - 7] + gamma1 + W[i - 16];
                }

                var ch  = (e & f) ^ (~e & g);
                var maj = (a & b) ^ (a & c) ^ (b & c);

                var sigma0 = ((a << 30) | (a >>> 2)) ^ ((a << 19) | (a >>> 13)) ^ ((a << 10) | (a >>> 22));
                var sigma1 = ((e << 26) | (e >>> 6)) ^ ((e << 21) | (e >>> 11)) ^ ((e << 7)  | (e >>> 25));

                var t1 = h + sigma1 + ch + K[i] + W[i];
                var t2 = sigma0 + maj;

                h = g;
                g = f;
                f = e;
                e = (d + t1) | 0;
                d = c;
                c = b;
                b = a;
                a = (t1 + t2) | 0;
            }

            // Intermediate hash value
            H[0] = (H[0] + a) | 0;
            H[1] = (H[1] + b) | 0;
            H[2] = (H[2] + c) | 0;
            H[3] = (H[3] + d) | 0;
            H[4] = (H[4] + e) | 0;
            H[5] = (H[5] + f) | 0;
            H[6] = (H[6] + g) | 0;
            H[7] = (H[7] + h) | 0;
        },

        _doFinalize: function () {
            // Shortcuts
            var data = this._data;
            var dataWords = data.words;

            var nBitsTotal = this._nDataBytes * 8;
            var nBitsLeft = data.sigBytes * 8;

            // Add padding
            dataWords[nBitsLeft >>> 5] |= 0x80 << (24 - nBitsLeft % 32);
            dataWords[(((nBitsLeft + 64) >>> 9) << 4) + 14] = Math.floor(nBitsTotal / 0x100000000);
            dataWords[(((nBitsLeft + 64) >>> 9) << 4) + 15] = nBitsTotal;
            data.sigBytes = dataWords.length * 4;

            // Hash final blocks
            this._process();

            // Return final computed hash
            return this._hash;
        },

        clone: function () {
            var clone = Hasher.clone.call(this);
            clone._hash = this._hash.clone();

            return clone;
        }
    });

    /**
     * Shortcut function to the hasher's object interface.
     *
     * @param {WordArray|string} message The message to hash.
     *
     * @return {WordArray} The hash.
     *
     * @static
     *
     * @example
     *
     *     var hash = CryptoJS.SHA256('message');
     *     var hash = CryptoJS.SHA256(wordArray);
     */
    C.SHA256 = Hasher._createHelper(SHA256);

    /**
     * Shortcut function to the HMAC's object interface.
     *
     * @param {WordArray|string} message The message to hash.
     * @param {WordArray|string} key The secret key.
     *
     * @return {WordArray} The HMAC.
     *
     * @static
     *
     * @example
     *
     *     var hmac = CryptoJS.HmacSHA256(message, key);
     */
    C.HmacSHA256 = Hasher._createHmacHelper(SHA256);
}(Math));

/** ..\vendors\hyperhtml-element.min.js **/
/*! (c) Andrea Giammarchi - ISC */
var HyperHTMLElement=function(t){"use strict";function e(t){return(e="function"==typeof Symbol&&"symbol"==typeof Symbol.iterator?function(t){return typeof t}:function(t){return t&&"function"==typeof Symbol&&t.constructor===Symbol&&t!==Symbol.prototype?"symbol":typeof t})(t)}function n(t,e){if(!(t instanceof e))throw new TypeError("Cannot call a class as a function")}function r(t,e){for(var n=0;n<e.length;n++){var r=e[n];r.enumerable=r.enumerable||!1,r.configurable=!0,"value"in r&&(r.writable=!0),Object.defineProperty(t,r.key,r)}}function i(t,e){if("function"!=typeof e&&null!==e)throw new TypeError("Super expression must either be null or a function");t.prototype=Object.create(e&&e.prototype,{constructor:{value:t,writable:!0,configurable:!0}}),e&&a(t,e)}function o(t){return(o=Object.setPrototypeOf?Object.getPrototypeOf:function(t){return t.__proto__||Object.getPrototypeOf(t)})(t)}function a(t,e){return(a=Object.setPrototypeOf||function(t,e){return t.__proto__=e,t})(t,e)}function u(t,e,n){return(u=function(){if("undefined"==typeof Reflect||!Reflect.construct)return!1;if(Reflect.construct.sham)return!1;if("function"==typeof Proxy)return!0;try{return Date.prototype.toString.call(Reflect.construct(Date,[],function(){})),!0}catch(t){return!1}}()?Reflect.construct:function(t,e,n){var r=[null];r.push.apply(r,e);var i=new(Function.bind.apply(t,r));return n&&a(i,n.prototype),i}).apply(null,arguments)}function c(t){var e="function"==typeof Map?new Map:void 0;return(c=function(t){if(null===t||(n=t,-1===Function.toString.call(n).indexOf("[native code]")))return t;var n;if("function"!=typeof t)throw new TypeError("Super expression must either be null or a function");if(void 0!==e){if(e.has(t))return e.get(t);e.set(t,r)}function r(){return u(t,arguments,o(this).constructor)}return r.prototype=Object.create(t.prototype,{constructor:{value:r,enumerable:!1,writable:!0,configurable:!0}}),a(r,t)})(t)}function l(t,e){return!e||"object"!=typeof e&&"function"!=typeof e?function(t){if(void 0===t)throw new ReferenceError("this hasn't been initialised - super() hasn't been called");return t}(t):e}var s={};try{s.WeakMap=WeakMap}catch(t){s.WeakMap=function(t,e){var n=e.defineProperty,r=e.hasOwnProperty,i=o.prototype;return i.delete=function(t){return this.has(t)&&delete t[this._]},i.get=function(t){return this.has(t)?t[this._]:void 0},i.has=function(t){return r.call(t,this._)},i.set=function(t,e){return n(t,this._,{configurable:!0,value:e}),this},o;function o(e){n(this,"_",{value:"_@ungap/weakmap"+t++}),e&&e.forEach(a,this)}function a(t){this.set(t[0],t[1])}}(Math.random(),Object)}var f=s.WeakMap,h={};try{h.WeakSet=WeakSet}catch(t){!function(t,e){var n=r.prototype;function r(){e(this,"_",{value:"_@ungap/weakmap"+t++})}n.add=function(t){return this.has(t)||e(t,this._,{value:!0,configurable:!0}),this},n.has=function(t){return this.hasOwnProperty.call(t,this._)},n.delete=function(t){return this.has(t)&&delete t[this._]},h.WeakSet=r}(Math.random(),Object.defineProperty)}var p=h.WeakSet,d={};try{d.Map=Map}catch(t){d.Map=function(){var t=0,e=[],n=[];return{delete:function(i){var o=r(i);return o&&(e.splice(t,1),n.splice(t,1)),o},get:function(e){return r(e)?n[t]:void 0},has:function(t){return r(t)},set:function(i,o){return n[r(i)?t:e.push(i)-1]=o,this}};function r(n){return-1<(t=e.indexOf(n))}}}var v=d.Map,b=function(t,e,n,r,i,o){if(i-r<2)e.insertBefore(t(n[r],1),o);else{for(var a=e.ownerDocument.createDocumentFragment();r<i;)a.appendChild(t(n[r++],1));e.insertBefore(a,o)}},m=function(t,e){return t==e},y=function(t){return t},g=function(t,e,n,r,i,o,a){var u=o-i;if(u<1)return-1;for(;n-e>=u;){for(var c=e,l=i;c<n&&l<o&&a(t[c],r[l]);)c++,l++;if(l===o)return e;e=c+1}return-1},w=function(t,e,n,r,i){return n<r?t(e[n],0):0<n?t(e[n-1],-0).nextSibling:i},E=function(t,e,n,r,i){if(i-r<2)e.removeChild(t(n[r],-1));else{var o=e.ownerDocument.createRange();o.setStartBefore(t(n[r],-1)),o.setEndAfter(t(n[i-1],-1)),o.deleteContents()}},_=function(t,e,n){for(var r=1,i=e;r<i;){var o=(r+i)/2>>>0;n<t[o]?i=o:r=o+1}return r},N=function(t,e,n,r,i,o,a,u,c,l,s,f,h){!function(t,e,n,r,i,o,a,u,c){for(var l=new v,s=t.length,f=a,h=0;h<s;)switch(t[h++]){case 0:i++,f++;break;case 1:l.set(r[i],1),b(e,n,r,i++,i,f<u?e(o[f],1):c);break;case-1:f++}for(h=0;h<s;)switch(t[h++]){case 0:a++;break;case-1:l.has(o[a])?a++:E(e,n,o,a++,a)}}(function(t,e,n,r,i,o,a){var u,c,l,s,f,h,p,d=n+o,v=[];t:for(u=0;u<=d;u++){if(u>50)return null;for(p=u-1,f=u?v[u-1]:[0,0],h=v[u]=[],c=-u;c<=u;c+=2){for(l=(s=c===-u||c!==u&&f[p+c-1]<f[p+c+1]?f[p+c+1]:f[p+c-1]+1)-c;s<o&&l<n&&a(r[i+s],t[e+l]);)s++,l++;if(s===o&&l===n)break t;h[u+c]=s}}var b=Array(u/2+d/2),m=b.length-1;for(u=v.length-1;u>=0;u--){for(;s>0&&l>0&&a(r[i+s-1],t[e+l-1]);)b[m--]=0,s--,l--;if(!u)break;p=u-1,f=u?v[u-1]:[0,0],(c=s-l)==-u||c!==u&&f[p+c-1]<f[p+c+1]?(l--,b[m--]=1):(s--,b[m--]=-1)}return b}(n,r,o,a,u,l,f)||function(t,e,n,r,i,o,a,u){var c=0,l=r<u?r:u,s=Array(l++),f=Array(l);f[0]=-1;for(var h=1;h<l;h++)f[h]=a;for(var p=new v,d=o;d<a;d++)p.set(i[d],d);for(var b=e;b<n;b++){var m=p.get(t[b]);null!=m&&-1<(c=_(f,l,m))&&(f[c]=m,s[c]={newi:b,oldi:m,prev:s[c-1]})}for(c=--l,--a;f[c]>a;)--c;l=u+r-c;var y=Array(l),g=s[c];for(--n;g;){for(var w=g,E=w.newi,N=w.oldi;n>E;)y[--l]=1,--n;for(;a>N;)y[--l]=-1,--a;y[--l]=0,--n,--a,g=g.prev}for(;n>=e;)y[--l]=1,--n;for(;a>=o;)y[--l]=-1,--a;return y}(n,r,i,o,a,u,c,l),t,e,n,r,a,u,s,h)},x=function(t,e,n,r){r||(r={});for(var i=r.compare||m,o=r.node||y,a=null==r.before?null:o(r.before,0),u=e.length,c=u,l=0,s=n.length,f=0;l<c&&f<s&&i(e[l],n[f]);)l++,f++;for(;l<c&&f<s&&i(e[c-1],n[s-1]);)c--,s--;var h=l===c,p=f===s;if(h&&p)return n;if(h&&f<s)return b(o,t,n,f,s,w(o,e,l,u,a)),n;if(p&&l<c)return E(o,t,e,l,c),n;var d=c-l,v=s-f,_=-1;if(d<v){if(-1<(_=g(n,f,s,e,l,c,i)))return b(o,t,n,f,_,o(e[l],0)),b(o,t,n,_+d,s,w(o,e,c,u,a)),n}else if(v<d&&-1<(_=g(e,l,c,n,f,s,i)))return E(o,t,e,l,_),E(o,t,e,_+v,c),n;return d<2||v<2?(b(o,t,n,f,s,o(e[l],0)),E(o,t,e,l,c),n):d===v&&function(t,e,n,r,i,o){for(;r<i&&o(n[r],t[e-1]);)r++,e--;return 0===e}(n,s,e,l,c,i)?(b(o,t,n,f,s,w(o,e,c,u,a)),n):(N(o,t,n,f,s,v,e,l,c,d,u,i,a),n)},k={};k.CustomEvent="function"==typeof CustomEvent?CustomEvent:function(t){return e.prototype=new e("").constructor.prototype,e;function e(t,e){e||(e={});var n=document.createEvent("CustomEvent");return n.initCustomEvent(t,!!e.bubbles,!!e.cancelable,e.detail),n}}();var C=k.CustomEvent;function S(){return this}var O,A,$=function(t,e){var n="_"+t+"$";return{get:function(){return this[n]||j(this,n,e.call(this,t))},set:function(t){j(this,n,t)}}},j=function(t,e,n){return Object.defineProperty(t,e,{configurable:!0,value:"function"==typeof n?function(){return t._wire$=n.apply(this,arguments)}:n})[e]},T={},M={},P=[],L=M.hasOwnProperty,R=0,D={attributes:T,define:function(t,e){t.indexOf("-")<0?(t in M||(R=P.push(t)),M[t]=e):T[t]=e},invoke:function(t,e){for(var n=0;n<R;n++){var r=P[n];if(L.call(t,r))return M[r](t[r],e)}}},W=Array.isArray||(A=(O={}.toString).call([]),function(t){return O.call(t)===A}),F=function(t){var e="fragment",n="content"in i("template")?function(t){var e=i("template");return e.innerHTML=t,e.content}:function(t){var n=i(e),o=i("template"),a=null;if(/^[^\S]*?<(col(?:group)?|t(?:head|body|foot|r|d|h))/i.test(t)){var u=RegExp.$1;o.innerHTML="<table>"+t+"</table>",a=o.querySelectorAll(u)}else o.innerHTML=t,a=o.childNodes;return r(n,a),n};return function(t,o){return("svg"===o?function(t){var n=i(e),o=i("div");return o.innerHTML='<svg xmlns="http://www.w3.org/2000/svg">'+t+"</svg>",r(n,o.firstChild.childNodes),n}:n)(t)};function r(t,e){for(var n=e.length;n--;)t.appendChild(e[0])}function i(n){return n===e?t.createDocumentFragment():t.createElementNS("http://www.w3.org/1999/xhtml",n)}}(document);var H,z=function(t,e,n,r,i){var o="importNode"in t,a=t.createDocumentFragment();return a.appendChild(t.createTextNode("g")),a.appendChild(t.createTextNode("")),(o?t.importNode(a,!0):a.cloneNode(!0)).childNodes.length<2?function t(e,n){for(var r=e.cloneNode(),i=e.childNodes||[],o=i.length,a=0;n&&a<o;a++)r.appendChild(t(i[a],n));return r}:o?t.importNode:function(t,e){return t.cloneNode(!!e)}}(document),Z="".trim||function(){return String(this).replace(/^\s+|\s+/g,"")},B="-"+Math.random().toFixed(6)+"%";"content"in(H=document.createElement("template"))&&(H.innerHTML='<p tabindex="'+B+'"></p>',H.content.childNodes[0].getAttribute("tabindex")==B)||(B="_dt: "+B.slice(1,-1)+";");var I="\x3c!--"+B+"--\x3e",V=8,G=1,q=3,K=/^(?:style|textarea)$/i,U=/^(?:area|base|br|col|embed|hr|img|input|keygen|link|menuitem|meta|param|source|track|wbr)$/i;var J=" \\f\\n\\r\\t",Q="[ "+J+"]+[^  \\f\\n\\r\\t\\/>\"'=]+",X="<([A-Za-z]+[A-Za-z0-9:_-]*)((?:",Y="(?:\\s*=\\s*(?:'[^']*?'|\"[^\"]*?\"|<[^>]*?>|[^  \\f\\n\\r\\t\\/>\"'=]+))?)",tt=new RegExp(X+Q+Y+"+)([ "+J+"]*/?>)","g"),et=new RegExp(X+Q+Y+"*)([ "+J+"]*/>)","g"),nt=new RegExp("("+Q+"\\s*=\\s*)(['\"]?)"+I+"\\2","gi");function rt(t,e,n,r){return"<"+e+n.replace(nt,it)+r}function it(t,e,n){return e+(n||'"')+B+(n||'"')}function ot(t,e,n){return U.test(e)?t:"<"+e+n+"></"+e+">"}function at(t,e,n,r){return{name:r,node:e,path:n,type:t}}function ut(t,e){for(var n=e.length,r=0;r<n;)t=t.childNodes[e[r++]];return t}function ct(t,e,n,r){for(var i=new v,o=t.attributes,a=[],u=a.slice.call(o,0),c=u.length,l=0;l<c;){var s=u[l++];if(s.value===B){var f=s.name;if(!i.has(f)){var h=n.shift().replace(/^(?:|[\S\s]*?\s)(\S+?)\s*=\s*['"]?$/,"$1"),p=o[h]||o[h.toLowerCase()];i.set(f,p),e.push(at("attr",p,r,h))}a.push(s)}}for(c=a.length,l=0;l<c;){var d=a[l++];/^id$/i.test(d.name)?t.removeAttribute(d.name):t.removeAttributeNode(d)}var b=t.nodeName;if(/^script$/i.test(b)){var m=document.createElement(b);for(c=o.length,l=0;l<c;)m.setAttributeNode(o[l++].cloneNode(!0));m.textContent=t.textContent,t.parentNode.replaceChild(m,t)}}var lt=new f,st=new f;function ft(t,e){var n=function(t){return t.join(I).replace(et,ot).replace(tt,rt)}(e),r=t.transform;r&&(n=r(n));var i=F(n,t.type);!function(t){var e=t.childNodes,n=e.length;for(;n--;){var r=e[n];1!==r.nodeType&&0===Z.call(r.textContent).length&&t.removeChild(r)}}(i);var o=[];!function t(e,n,r,i){for(var o=e.childNodes,a=o.length,u=0;u<a;){var c=o[u];switch(c.nodeType){case G:var l=i.concat(u);ct(c,n,r,l),t(c,n,r,l);break;case V:c.textContent===B&&(r.shift(),n.push(K.test(e.nodeName)?at("text",e,i):at("any",c,i.concat(u))));break;case q:K.test(e.nodeName)&&Z.call(c.textContent)===I&&(r.shift(),n.push(at("text",e,i)))}u++}}(i,o,e.slice(0),[]);var a={content:i,updates:function(n){for(var r=[],i=o.length,a=0;a<i;){var u=o[a++],c=ut(n,u.path);switch(u.type){case"any":r.push(t.any(c,[]));break;case"attr":r.push(t.attribute(c,u.name,u.node));break;case"text":r.push(t.text(c)),c.textContent=""}}return function(){var t=arguments.length,o=t-1,a=1;if(i!==o)throw new Error(o+" values instead of "+i+"\n"+e.join(", "));for(;a<t;)r[a-1](arguments[a++]);return n}}};return lt.set(e,a),a}function ht(t){return function(e){var n=st.get(t);return null!=n&&n.template===e||(n=function(t,e){var n=lt.get(e)||ft(t,e),r=z.call(document,n.content,!0),i={content:r,template:e,updates:n.updates(r)};return st.set(t,i),i}(t,e)),n.updates.apply(null,arguments),n.content}}var pt,dt,vt=function(){var t=/acit|ex(?:s|g|n|p|$)|rph|ows|mnc|ntw|ine[ch]|zoo|^ord/i,n=/([^A-Z])([A-Z]+)/g;return function(t,e){return"ownerSVGElement"in t?function(t,e){var n;e?n=e.cloneNode(!0):(t.setAttribute("style","--hyper:style;"),n=t.getAttributeNode("style"));return n.value="",t.setAttributeNode(n),i(n,!0)}(t,e):i(t.style,!1)};function r(t,e,n){return e+"-"+n.toLowerCase()}function i(i,o){var a,u;return function(c){var l,s,f,h;switch(e(c)){case"object":if(c){if("object"===a){if(!o&&u!==c)for(s in u)s in c||(i[s]="")}else o?i.value="":i.cssText="";for(s in l=o?{}:i,c)f="number"!=typeof(h=c[s])||t.test(s)?h:h+"px",!o&&/^--/.test(s)?l.setProperty(s,f):l[s]=f;a="object",o?i.value=function(t){var e,i=[];for(e in t)i.push(e.replace(n,r),":",t[e],";");return i.join("")}(u=l):u=c;break}default:u!=c&&(a="string",u=c,o?i.value=c||"":i.cssText=c||"")}}}}(),bt=document.defaultView,mt="ownerSVGElement",yt=(pt=!1,dt=function(t){if(!("raw"in t)||t.propertyIsEnumerable("raw")||!Object.isFrozen(t.raw)||/Firefox\/(\d+)/.test((document.defaultView.navigator||{}).userAgent)&&parseFloat(RegExp.$1)<55){var e={};return(dt=function(t){var n="raw"+t.join("raw");return e[n]||(e[n]=t)})(t)}return pt=!0,t},function(t){return pt?t:dt(t)}),gt=function(t){return t.ownerDocument||t},wt=function(t){return gt(t).createDocumentFragment()},Et="append"in wt(document)?function(t,e){t.append.apply(t,e)}:function(t,e){for(var n=e.length,r=0;r<n;r++)t.appendChild(e[r])},_t=function(t){for(var e=[yt(t)],n=1,r=arguments.length;n<r;n++)e[n]=arguments[n];return e},Nt=[].slice;function xt(t){this.childNodes=t,this.length=t.length,this.first=t[0],this.last=t[this.length-1],this._=null}xt.prototype.valueOf=function(t){var e=null==this._;return e&&(this._=wt(this.first)),(e||t)&&Et(this._,this.childNodes),this._},xt.prototype.remove=function(){this._=null;var t=this.first,e=this.last;if(2===this.length)e.parentNode.removeChild(e);else{var n=gt(t).createRange();n.setStartBefore(this.childNodes[1]),n.setEndAfter(e),n.deleteContents()}return t};var kt=function(t){var e="connected",n="dis"+e,r=t.Event,i=t.WeakSet,o=!0,a=new i;return function(t){return o&&(o=!o,function(t){var o=null;try{new MutationObserver(s).observe(t,{subtree:!0,childList:!0})}catch(e){var u=0,c=[],l=function(t){c.push(t),clearTimeout(u),u=setTimeout(function(){s(c.splice(u=0,c.length))},0)};t.addEventListener("DOMNodeRemoved",function(t){l({addedNodes:[],removedNodes:[t.target]})},!0),t.addEventListener("DOMNodeInserted",function(t){l({addedNodes:[t.target],removedNodes:[]})},!0)}function s(t){o=new function(){this[e]=new i,this[n]=new i};for(var r,a=t.length,u=0;u<a;u++)f((r=t[u]).removedNodes,n,e),f(r.addedNodes,e,n);o=null}function f(t,e,n){for(var i,o=new r(e),a=t.length,u=0;u<a;1===(i=t[u++]).nodeType&&h(i,o,e,n));}function h(t,e,n,r){a.has(t)&&!o[n].has(t)&&(o[r].delete(t),o[n].add(t),t.dispatchEvent(e));for(var i=t.children||[],u=i.length,c=0;c<u;h(i[c++],e,n,r));}}(t.ownerDocument)),a.add(t),t}}({Event:C,WeakSet:p}),Ct=function(t){return{html:t}},St=function t(e,n){return"ELEMENT_NODE"in e?e:e.constructor===xt?1/n<0?n?e.remove():e.last:n?e.valueOf(!0):e.first:t(e.render(),n)},Ot=function(t,e){e(t.placeholder),"text"in t?Promise.resolve(t.text).then(String).then(e):"any"in t?Promise.resolve(t.any).then(e):"html"in t?Promise.resolve(t.html).then(Ct).then(e):Promise.resolve(D.invoke(t,e)).then(e)},At=function(t){return null!=t&&"then"in t},$t=/^(?:form|list)$/i;function jt(t){return this.type=t,ht(this)}jt.prototype={attribute:function(t,e,n){var r,i=mt in t;if("style"===e)return vt(t,n,i);if(/^on/.test(e)){var o=e.slice(2);return"connected"===o||"disconnected"===o?kt(t):e.toLowerCase()in t&&(o=o.toLowerCase()),function(e){r!==e&&(r&&t.removeEventListener(o,r,!1),r=e,e&&t.addEventListener(o,e,!1))}}if("data"===e||!i&&e in t&&!$t.test(e))return function(n){r!==n&&(r=n,t[e]!==n&&(t[e]=n,null==n&&t.removeAttribute(e)))};if(e in D.attributes)return function(n){r=D.attributes[e](t,n),t.setAttribute(e,null==r?"":r)};var a=!1,u=n.cloneNode(!0);return function(e){r!==e&&(r=e,u.value!==e&&(null==e?(a&&(a=!1,t.removeAttributeNode(u)),u.value=e):(u.value=e,a||(a=!0,t.setAttributeNode(u)))))}},any:function(t,n){var r,i={node:St,before:t},o=mt in t?"svg":"html",a=!1;return function u(c){switch(e(c)){case"string":case"number":case"boolean":a?r!==c&&(r=c,n[0].textContent=c):(a=!0,r=c,n=x(t.parentNode,n,[function(t,e){return gt(t).createTextNode(e)}(t,c)],i));break;case"function":u(c(t));break;case"object":case"undefined":if(null==c){a=!1,n=x(t.parentNode,n,[],i);break}default:if(a=!1,r=c,W(c))if(0===c.length)n.length&&(n=x(t.parentNode,n,[],i));else switch(e(c[0])){case"string":case"number":case"boolean":u({html:c});break;case"object":if(W(c[0])&&(c=c.concat.apply([],c)),At(c[0])){Promise.all(c).then(u);break}default:n=x(t.parentNode,n,c,i)}else!function(t){return"ELEMENT_NODE"in t||t instanceof xt||t instanceof S}(c)?At(c)?c.then(u):"placeholder"in c?Ot(c,u):"text"in c?u(String(c.text)):"any"in c?u(c.any):"html"in c?n=x(t.parentNode,n,Nt.call(F([].concat(c.html).join(""),o).childNodes),i):u("length"in c?Nt.call(c):D.invoke(c,u)):n=x(t.parentNode,n,11===c.nodeType?Nt.call(c.childNodes):[c],i)}}},text:function(t){var n;return function r(i){if(n!==i){n=i;var o=e(i);"object"===o&&i?At(i)?i.then(r):"placeholder"in i?Ot(i,r):r("text"in i?String(i.text):"any"in i?i.any:"html"in i?[].concat(i.html).join(""):"length"in i?Nt.call(i).join(""):D.invoke(i,r)):"function"===o?r(i(t)):t.textContent=null==i?"":i}}}};var Tt=new f,Mt=function(t,e){return null==t?Pt(e||"html"):Lt(t,e||"html")},Pt=function(t){var e,n,r;return function(){var i=_t.apply(null,arguments);return r!==i[0]?(r=i[0],n=new jt(t),e=Rt(n.apply(n,i))):n.apply(n,i),e}},Lt=function(t,e){var n=e.indexOf(":"),r=Tt.get(t),i=e;return-1<n&&(i=e.slice(n+1),e=e.slice(0,n)||"html"),r||Tt.set(t,r={}),r[i]||(r[i]=Pt(e))},Rt=function(t){var e=t.childNodes;return 1===e.length?e[0]:new xt(Nt.call(e,0))},Dt=new f;function Wt(){var t=Dt.get(this),e=_t.apply(null,arguments);return t&&t.template===e[0]?t.tagger.apply(null,e):function(){var t=_t.apply(null,arguments),e=new jt(mt in this?"svg":"html");Dt.set(this,{tagger:e,template:t[0]}),this.textContent="",this.appendChild(e.apply(null,t))}.apply(this,e),this}var Ft=function(t){return Wt.bind(t)},Ht=D.define,zt=jt.prototype;function Zt(t){return arguments.length<2?null==t?Pt("html"):"string"==typeof t?Zt.wire(null,t):"raw"in t?Pt("html")(t):"nodeType"in t?Zt.bind(t):Lt(t,"html"):("raw"in t?Pt("html"):Zt.wire).apply(null,arguments)}Zt.Component=S,Zt.bind=Ft,Zt.define=Ht,Zt.diff=x,Zt.hyper=Zt,Zt.observe=kt,Zt.tagger=zt,Zt.wire=Mt,Zt._={global:bt,WeakMap:f,WeakSet:p},function(t){var n=new f,r=Object.create,i=function(t,e){var n={w:null,p:null};return e.set(t,n),n};Object.defineProperties(S,{for:{configurable:!0,value:function(t,o){return function(t,n,o,a){var u=n.get(t)||i(t,n);switch(e(a)){case"object":case"function":var c=u.w||(u.w=new f);return c.get(a)||function(t,e,n){return t.set(e,n),n}(c,a,new t(o));default:var l=u.p||(u.p=r(null));return l[a]||(l[a]=new t(o))}}(this,n.get(t)||function(t){var e=new v;return n.set(t,e),e}(t),t,null==o?"default":o)}}}),Object.defineProperties(S.prototype,{handleEvent:{value:function(t){var e=t.currentTarget;this["getAttribute"in e&&e.getAttribute("data-call")||"on"+t.type](t)}},html:$("html",t),svg:$("svg",t),state:$("state",function(){return this.defaultState}),defaultState:{get:function(){return{}}},dispatch:{value:function(t,e){var n=this._wire$;if(n){var r=new C(t,{bubbles:!0,cancelable:!0,detail:e});return r.component=this,(n.dispatchEvent?n:n.childNodes[0]).dispatchEvent(r)}return!1}},setState:{value:function(t,e){var n=this.state,r="function"==typeof t?t.call(this,n):t;for(var i in r)n[i]=r[i];return!1!==e&&this.render(),this}}})}(Pt);var Bt=Object,It=[],Vt=Bt.defineProperty,Gt=Bt.getOwnPropertyDescriptor,qt=Bt.getOwnPropertyNames,Kt=Bt.getOwnPropertySymbols||function(){return[]},Ut=Bt.getPrototypeOf||function(t){return t.__proto__},Jt="object"===("undefined"==typeof Reflect?"undefined":e(Reflect))&&Reflect.ownKeys||function(t){return qt(t).concat(Kt(t))},Qt=Bt.setPrototypeOf||function(t,e){return t.__proto__=e,t},Xt=function(t){return t.replace(/-([a-z])/g,function(t,e){return e.toUpperCase()})},Yt=function(t){function e(){return n(this,e),l(this,o(e).apply(this,arguments))}var a,u,s;return i(e,c(HTMLElement)),a=e,s=[{key:"define",value:function(t,e){var r=this.prototype,a=r.attributeChangedCallback,u=!!a,c=this.booleanAttributes||[];c.forEach(function(t){t in r||Vt(r,Xt(t),{configurable:!0,get:function(){return this.hasAttribute(t)},set:function(e){e&&"false"!==e?this.setAttribute(t,e):this.removeAttribute(t)}})});var s=this.observedAttributes||[];s.forEach(function(t){t in r||Vt(r,Xt(t),{configurable:!0,get:function(){return this.getAttribute(t)},set:function(e){null==e?this.removeAttribute(t):this.setAttribute(t,e)}})});var f=c.concat(s);f.length&&Vt(this,"observedAttributes",{get:function(){return f}});var h=r.created||function(){this.render()};Vt(r,"_init$",{configurable:!0,writable:!0,value:!0}),Vt(r,"attributeChangedCallback",{configurable:!0,value:function t(e,n,r){if(this._init$&&(ee.call(this,h),this._init$))return this._init$$.push(t.bind(this,e,n,r));u&&n!==r&&a.apply(this,arguments)}});var p=r.connectedCallback,d=!!p;if(Vt(r,"connectedCallback",{configurable:!0,value:function t(){if(this._init$&&(ee.call(this,h),this._init$))return this._init$$.push(t.bind(this));d&&p.apply(this,arguments)}}),qt(r).forEach(function(t){if(/^handle[A-Z]/.test(t)){var e="_"+t+"$",n=r[t];Vt(r,t,{configurable:!0,get:function(){return this[e]||(this[e]=n.bind(this))}})}}),"handleEvent"in r||Vt(r,"handleEvent",{configurable:!0,value:function(t){this[(t.currentTarget.dataset||{}).call||"on"+t.type](t)}}),e&&e.extends){var v=document.createElement(e.extends).constructor,b=function(t){function e(){return n(this,e),l(this,o(e).apply(this,arguments))}return i(e,v),e}(),m=Ut(this);Jt(m).filter(function(t){return["length","name","arguments","caller","prototype"].indexOf(t)<0}).forEach(function(t){return Vt(b,t,Gt(m,t))}),Jt(m.prototype).forEach(function(t){return Vt(b.prototype,t,Gt(m.prototype,t))}),Qt(this,b),Qt(r,b.prototype),customElements.define(t,this,e)}else customElements.define(t,this);return It.push(this),this}}],(u=[{key:"render",value:function(){}},{key:"setState",value:function(t,e){var n=this.state,r="function"==typeof t?t.call(this,n):t;for(var i in r)n[i]=r[i];return!1!==e&&this.render(),this}},{key:"html",get:function(){return this._html$||(this.html=Ft(this.shadowRoot||this._shadowRoot||this))},set:function(t){Vt(this,"_html$",{configurable:!0,value:t})}},{key:"defaultState",get:function(){return{}}},{key:"state",get:function(){return this._state$||(this.state=this.defaultState)},set:function(t){Vt(this,"_state$",{configurable:!0,value:t})}}])&&r(a.prototype,u),s&&r(a,s),e}();Yt.Component=S,Yt.bind=Ft,Yt.intent=Ht,Yt.wire=Mt,Yt.hyper=Zt;try{Symbol.hasInstance&&It.push(Vt(Yt,Symbol.hasInstance,{enumerable:!1,configurable:!0,value:function(t){return It.some(re,Ut(t))}}))}catch(t){}var te={type:"DOMContentLoaded",handleEvent:function(){te.ready()?(document.removeEventListener(te.type,te,!1),te.list.splice(0).forEach(ne)):setTimeout(te.handleEvent)},ready:function(){return"complete"===document.readyState},list:[]};function ee(t){if(te.ready()||function(t){var e=this;do{if(e.nextSibling)return!0}while(e=e.parentNode);return setTimeout(ee.bind(this,t)),!1}.call(this,t)){if(this._init$){var e=this._init$$;e&&delete this._init$$,t.call(Vt(this,"_init$",{value:!1})),e&&e.forEach(ne)}}else this.hasOwnProperty("_init$$")||Vt(this,"_init$$",{configurable:!0,value:[]}),te.list.push(ee.bind(this,t))}function ne(t){t()}function re(t){return this===t.prototype}return te.ready()||document.addEventListener(te.type,te,!1),t.default=Yt,t.default}({});

/** ..\vendors\inferno.min.js **/
!function(e,n){"object"==typeof exports&&"undefined"!=typeof module?n(exports):"function"==typeof define&&define.amd?define(["exports"],n):n(e.Inferno=e.Inferno||{})}(this,function(e){"use strict";var f=Array.isArray;function d(e){var n=typeof e;return"string"===n||"number"===n}function F(e){return v(e)||w(e)}function b(e){return w(e)||!1===e||!0===e||v(e)}function C(e){return"function"==typeof e}function p(e){return"string"==typeof e}function w(e){return null===e}function v(e){return void 0===e}function P(e,n){var t={};if(e)for(var r in e)t[r]=e[r];if(n)for(var l in n)t[l]=n[l];return t}var L={};function N(e,n){e.appendChild(n)}function h(e,n,t){w(t)?N(e,n):e.insertBefore(n,t)}function x(e,n){e.removeChild(n)}function a(e){for(var n;void 0!==(n=e.shift());)n()}function U(e,n){for(var t,r;e;){if(2033&(t=e.flags))return e.dom;r=e.children,e=8192&t?2===e.childFlags?r:r[n?0:r.length-1]:4&t?r.$LI:r}return null}function S(e,n){var t=e.flags;if(2033&t)x(n,e.dom);else{var r=e.children;if(4&t)S(r.$LI,n);else if(8&t)S(r,n);else if(8192&t)if(2===e.childFlags)S(r,n);else for(var l=0,o=r.length;l<o;++l)S(r[l],n)}}function V(e,n,t){var r=e.flags;if(2033&r)h(n,e.dom,t);else{var l=e.children;if(4&r)V(l.$LI,n,t);else if(8&r)V(l,n,t);else if(8192&r)if(2===e.childFlags)V(l,n,t);else for(var o=0,a=l.length;o<a;++o)V(l[o],n,t)}}function k(e,n,t){return e.constructor.getDerivedStateFromProps?P(t,e.constructor.getDerivedStateFromProps(n,t)):t}var i={v:!1},g={componentComparator:null,createVNode:null,renderComplete:null},m="$";function y(e,n,t,r,l,o,a,i){this.childFlags=e,this.children=n,this.className=t,this.dom=null,this.flags=r,this.key=void 0===l?null:l,this.props=void 0===o?null:o,this.ref=void 0===a?null:a,this.type=i}function l(e,n,t,r,l,o,a,i){var s=void 0===l?1:l,c=new y(s,r,t,e,a,o,i,n),u=g.createVNode;return C(u)&&u(c),0===s&&_(c,c.children),c}function $(e,n){return new y(1,F(e)?"":e,null,16,n,null,null,null)}function s(e,n,t){var r=l(8192,8192,null,e,n,null,t,null);switch(r.childFlags){case 1:r.children=B(),r.childFlags=2;break;case 16:r.children=[$(e)],r.childFlags=4}return r}function M(e){var n=-81921&e.flags,t=e.props;if(14&n&&!w(t)){var r=t;for(var l in t={},r)t[l]=r[l]}return 0==(8192&n)?new y(e.childFlags,e.children,e.className,n,e.key,t,e.ref,e.type):function(e){var n,t=e.children,r=e.childFlags;if(2===r)n=M(t);else if(12&r){n=[];for(var l=0,o=t.length;l<o;++l)n.push(M(t[l]))}return s(n,r,e.key)}(e)}function B(){return $("",null)}function I(e,n,t,r){for(var l=e.length;t<l;t++){var o=e[t];if(!b(o)){var a=r+m+t;if(f(o))I(o,n,0,a);else{if(d(o))o=$(o,a);else{var i=o.key,s=p(i)&&i[0]===m;(81920&o.flags||s)&&(o=M(o)),o.flags|=65536,w(i)||s?o.key=a:o.key=r+i}n.push(o)}}}}function _(e,n){var t,r=1;if(b(n))t=n;else if(d(n))r=16,t=n;else if(f(n)){for(var l=n.length,o=0;o<l;++o){var a=n[o];if(b(a)||f(a)){I(n,t=t||n.slice(0,o),o,"");break}if(d(a))(t=t||n.slice(0,o)).push($(a,m+o));else{var i=a.key,s=0<(81920&a.flags),c=w(i),u=!c&&p(i)&&i[0]===m;s||c||u?(t=t||n.slice(0,o),(s||u)&&(a=M(a)),(c||u)&&(a.key=m+o),t.push(a)):t&&t.push(a),a.flags|=65536}}r=0===(t=t||n).length?1:8}else(t=n).flags|=65536,81920&n.flags&&(t=M(n)),r=2;return e.children=t,e.childFlags=r,e}var n="http://www.w3.org/1999/xlink",t="http://www.w3.org/XML/1998/namespace",D={"xlink:actuate":n,"xlink:arcrole":n,"xlink:href":n,"xlink:role":n,"xlink:show":n,"xlink:title":n,"xlink:type":n,"xml:base":t,"xml:lang":t,"xml:space":t};function c(e){return{onClick:e,onDblClick:e,onFocusIn:e,onFocusOut:e,onKeyDown:e,onKeyPress:e,onKeyUp:e,onMouseDown:e,onMouseMove:e,onMouseUp:e,onSubmit:e,onTouchEnd:e,onTouchMove:e,onTouchStart:e}}var u=c(0),T=c(null),E=c(!0);function W(e,n,t){var r,l,o=t.$EV;n?(0===u[e]&&(T[e]=(r=e,l=function(e){var n="onClick"===r||"onDblClick"===r;if(n&&0!==e.button)e.stopPropagation();else{e.stopPropagation=A;var t={dom:document};Object.defineProperty(e,"currentTarget",{configurable:!0,get:function(){return t.dom}}),function(e,n,t,r,l){for(var o=n;!w(o);){if(t&&o.disabled)return;var a=o.$EV;if(a){var i=a[r];if(i&&(l.dom=o,i.event?i.event(i.data,e):i(e),e.cancelBubble))return}o=o.parentNode}}(e,e.target,n,r,t)}},document.addEventListener(R(r),l),l)),o||(o=t.$EV=c(null)),o[e]||++u[e],o[e]=n):o&&o[e]&&(0==--u[e]&&(document.removeEventListener(R(e),T[e]),T[e]=null),o[e]=null)}function R(e){return e.substr(2).toLowerCase()}function A(){this.cancelBubble=!0,this.immediatePropagationStopped||this.stopImmediatePropagation()}function O(e,n,t){if(e[n]){var r=e[n];r.event?r.event(r.data,t):r(t)}else{var l=n.toLowerCase();e[l]&&e[l](t)}}function r(i,s){var e=function(e){var n=this.$V;if(n){var t=n.props||L,r=n.dom;if(p(i))O(t,i,e);else for(var l=0;l<i.length;++l)O(t,i[l],e);if(C(s)){var o=this.$V,a=o.props||L;s(a,r,!1,o)}}};return Object.defineProperty(e,"wrapped",{configurable:!1,enumerable:!1,value:!0,writable:!1}),e}function j(e){return"checkbox"===e||"radio"===e}var H=r("onInput",G),Q=r(["onClick","onChange"],G);function X(e){e.stopPropagation()}function G(e,n){var t=e.type,r=e.value,l=e.checked,o=e.multiple,a=e.defaultValue,i=!F(r);t&&t!==n.type&&n.setAttribute("type",t),F(o)||o===n.multiple||(n.multiple=o),F(a)||i||(n.defaultValue=a+""),j(t)?(i&&(n.value=r),F(l)||(n.checked=l)):i&&n.value!==r?(n.defaultValue=r,n.value=r):F(l)||(n.checked=l)}X.wrapped=!0;var K=r("onChange",q);function q(e,n,t,r){var l=Boolean(e.multiple);if(F(e.multiple)||l===n.multiple||(n.multiple=l),1!==r.childFlags){var o=e.value;t&&F(o)&&(o=e.defaultValue),function e(n,t){if("option"===n.type)s=t,c=(i=n).props||L,(u=i.dom).value=c.value,c.value===s||f(s)&&-1!==s.indexOf(c.value)?u.selected=!0:F(s)&&F(c.selected)||(u.selected=c.selected||!1);else{var r=n.children,l=n.flags;if(4&l)e(r.$LI,t);else if(8&l)e(r,t);else if(2===n.childFlags)e(r,t);else if(12&n.childFlags)for(var o=0,a=r.length;o<a;++o)e(r[o],t)}var i,s,c,u}(r,o)}}var z=r("onInput",Y),J=r("onChange");function Y(e,n,t){var r=e.value,l=n.value;if(F(r)){if(t){var o=e.defaultValue;F(o)||o===l||(n.defaultValue=o,n.value=o)}}else l!==r&&(n.defaultValue=r,n.value=r)}function Z(e,n,t,r,l,o){64&e?G(r,t):256&e?q(r,t,l,n):128&e&&Y(r,t,l),o&&(t.$V=n)}function ee(e){return e.type&&j(e.type)?!F(e.checked):!F(e.value)}function ne(e){e&&(C(e)?e(null):e.current&&(e.current=null))}function te(e,n,t){var r,l;e&&(C(e)?(r=n,l=e,t.push(function(){l(r)})):void 0!==e.current&&(e.current=n))}function re(e,n){le(e),n&&S(e,n)}function le(e){var n,t=e.flags,r=e.children;if(481&t){n=e.ref;var l=e.props;ne(n);var o=e.childFlags;if(!w(l))for(var a=Object.keys(l),i=0,s=a.length;i<s;i++){var c=a[i];E[c]&&W(c,null,e.dom)}12&o?oe(r):2===o&&le(r)}else r&&(4&t?(C(r.componentWillUnmount)&&r.componentWillUnmount(),ne(e.ref),r.$UN=!0,le(r.$LI)):8&t?(!F(n=e.ref)&&C(n.onComponentWillUnmount)&&n.onComponentWillUnmount(U(e,!0),e.props||L),le(r)):1024&t?re(r,e.ref):8192&t&&12&e.childFlags&&oe(r))}function oe(e){for(var n=0,t=e.length;n<t;++n)le(e[n])}function ae(e){e.textContent=""}function ie(e,n,t){oe(t),8192&n.flags?S(n,e):ae(e)}function se(s,e,n,t,r,l,o){switch(s){case"children":case"childrenType":case"className":case"defaultValue":case"key":case"multiple":case"ref":break;case"autoFocus":t.autofocus=!!n;break;case"allowfullscreen":case"autoplay":case"capture":case"checked":case"controls":case"default":case"disabled":case"hidden":case"indeterminate":case"loop":case"muted":case"novalidate":case"open":case"readOnly":case"required":case"reversed":case"scoped":case"seamless":case"selected":t[s]=!!n;break;case"defaultChecked":case"value":case"volume":if(l&&"value"===s)break;var a=F(n)?"":n;t[s]!==a&&(t[s]=a);break;case"style":!function(e,n,t){if(F(n))t.removeAttribute("style");else{var r,l,o=t.style;if(p(n))o.cssText=n;else if(F(e)||p(e))for(r in n)l=n[r],o.setProperty(r,l);else{for(r in n)(l=n[r])!==e[r]&&o.setProperty(r,l);for(r in e)F(n[r])&&o.removeProperty(r)}}}(e,n,t);break;case"dangerouslySetInnerHTML":var i=e&&e.__html||"",c=n&&n.__html||"";i!==c&&(F(c)||(u=t,f=c,(d=document.createElement("i")).innerHTML=f,d.innerHTML===u.innerHTML)||(w(o)||(12&o.childFlags?oe(o.children):2===o.childFlags&&le(o.children),o.children=null,o.childFlags=1),t.innerHTML=c));break;default:E[s]?e&&n&&!C(e)&&!C(n)&&e.event===n.event&&e.data===n.data||W(s,n,t):111===s.charCodeAt(0)&&110===s.charCodeAt(1)?function(e,n,t){var r,l,o=s.toLowerCase();if(C(n)||F(n)){var a=t[o];a&&a.wrapped||(t[o]=n)}else{var i=n.event;C(i)&&(t[o]=(r=i,l=n,function(e){r(l.data,e)}))}}(0,n,t):F(n)?t.removeAttribute(s):r&&D[s]?t.setAttributeNS(D[s],s,n):t.setAttribute(s,n)}var u,f,d}function ce(e,n,t,r,l){var o,a,i,s,c,u,f=!1,d=0<(448&n);for(var p in d&&(f=ee(t))&&(a=r,i=t,u=c=s=void 0,64&(o=n)?(u=a,j(i.type)?(u.onchange=Q,u.onclick=X):u.oninput=H):256&o?a.onchange=K:128&o&&(c=i,(s=a).oninput=z,c.onChange&&(s.onchange=J))),t)se(p,null,t[p],r,l,f,null);d&&Z(n,e,r,t,!0,f)}function ue(e,n,t){var r=de(e.render(n,e.state,t)),l=t;return C(e.getChildContext)&&(l=P(t,e.getChildContext())),e.$CX=l,r}function fe(e,n,t,r,l,o){var a=new n(t,r),i=a.$N=Boolean(n.getDerivedStateFromProps||a.getSnapshotBeforeUpdate);if(a.$SVG=l,a.$L=o,(e.children=a).$BS=!1,a.context=r,a.props===L&&(a.props=t),i)a.state=k(a,t,a.state);else if(C(a.componentWillMount)){a.$BR=!0,a.componentWillMount();var s=a.$PS;if(!w(s)){var c=a.state;if(w(c))a.state=s;else for(var u in s)c[u]=s[u];a.$PS=null}a.$BR=!1}return a.$LI=ue(a,t,r),a}function de(e){return b(e)?e=B():d(e)?e=$(e,null):f(e)?e=s(e,0,null):16384&e.flags&&(e=M(e)),e}function pe(e,n,t,r,l,o){var a,i,s,c,u,f,d,p,v,h,g,m,y,k,$,b,C,F,w,P,N,x,S,U,V,M=e.flags|=16384;481&M?ge(e,n,t,r,l,o):4&M?(m=n,y=t,k=r,$=l,b=o,pe((C=fe(g=e,g.type,g.props||L,y,k,b)).$LI,m,C.$CX,k,$,b),ye(g.ref,C,b)):8&M?(i=n,s=t,c=r,u=l,f=o,d=(a=e).type,p=a.props||L,v=a.ref,h=de(32768&a.flags?d(p,v,s):d(p,s)),pe(a.children=h,i,s,c,u,f),ke(p,v,a,f)):512&M||16&M?ve(e,n,l):8192&M?(w=n,P=t,N=r,x=l,S=o,U=(F=e).children,12&(V=F.childFlags)&&0===U.length&&(V=F.childFlags=2,U=F.children=B()),2===V?pe(U,w,x,N,x,S):me(U,w,P,N,x,S)):1024&M&&function(e,n,t,r,l){pe(e.children,e.ref,n,!1,null,l);var o=B();ve(o,t,r),e.dom=o.dom}(e,t,n,l,o)}function ve(e,n,t){var r=e.dom=document.createTextNode(e.children);w(n)||h(n,r,t)}function he(e,n){e.textContent=n}function ge(e,n,t,r,l,o){var a=e.flags,i=e.props,s=e.className,c=e.ref,u=e.children,f=e.childFlags;r=r||0<(32&a);var d,p=(d=e.type,r?document.createElementNS("http://www.w3.org/2000/svg",d):document.createElement(d));if(e.dom=p,F(s)||""===s||(r?p.setAttribute("class",s):p.className=s),16===f)he(p,u);else if(1!==f){var v=r&&"foreignObject"!==e.type;2===f?(16384&u.flags&&(e.children=u=M(u)),pe(u,p,t,v,null,o)):8!==f&&4!==f||me(u,p,t,v,null,o)}w(n)||h(n,p,l),w(i)||ce(e,a,i,p,r),te(c,p,o)}function me(e,n,t,r,l,o){for(var a=0,i=e.length;a<i;++a){var s=e[a];16384&s.flags&&(e[a]=s=M(s)),pe(s,n,t,r,l,o)}}function ye(e,n,t){var r;te(e,n,t),C(n.componentDidMount)&&t.push((r=n,function(){r.componentDidMount()}))}function ke(e,n,t,r){var l,o,a;F(n)||(C(n.onComponentWillMount)&&n.onComponentWillMount(e),C(n.onComponentDidMount)&&r.push((l=n,o=t,a=e,function(){l.onComponentDidMount(U(o,!0),a)})))}function $e(e,n,t,r,l,o,a){var i,s,c,u,f,d,p,v,h,g,m,y,k,$=n.flags|=16384;e.flags!==$||e.type!==n.type||e.key!==n.key||0!=(2048&$)?16384&e.flags?(s=n,c=t,u=r,f=l,d=a,le(i=e),0!=(s.flags&i.flags&2033)?(pe(s,null,u,f,null,d),p=c,v=s.dom,h=i.dom,p.replaceChild(v,h)):(pe(s,c,u,f,U(i,!0),d),S(i,c))):pe(n,t,r,l,o,a):481&$?function(e,n,t,r,l,o){var a,i=e.dom,s=e.props,c=n.props,u=!1,f=!1;if(n.dom=i,r=r||0<(32&l),s!==c){var d=s||L;if((a=c||L)!==L)for(var p in(u=0<(448&l))&&(f=ee(a)),a){var v=d[p],h=a[p];v!==h&&se(p,v,h,i,r,f,e)}if(d!==L)for(var g in d)F(a[g])&&!F(d[g])&&se(g,d[g],null,i,r,f,e)}var m,y,k=n.children,$=n.className;e.className!==$&&(F($)?i.removeAttribute("class"):r?i.setAttribute("class",$):i.className=$),4096&l?(y=k,(m=i).textContent!==y&&(m.textContent=y)):be(e.childFlags,n.childFlags,e.children,k,i,t,r&&"foreignObject"!==n.type,null,e,o),u&&Z(l,n,i,a,!1,f);var b=n.ref,C=e.ref;C!==b&&(ne(C),te(b,i,o))}(e,n,r,l,$,a):4&$?function(e,n,t,r,l,o,a){var i=n.children=e.children;if(!w(i)){i.$L=a;var s=n.props||L,c=n.ref,u=e.ref,f=i.state;if(!i.$N){if(C(i.componentWillReceiveProps)){if(i.$BR=!0,i.componentWillReceiveProps(s,r),i.$UN)return;i.$BR=!1}w(i.$PS)||(f=P(f,i.$PS),i.$PS=null)}Ce(i,f,s,t,r,l,!1,o,a),u!==c&&(ne(u),te(c,i,a))}}(e,n,t,r,l,o,a):8&$?function(e,n,t,r,l,o,a){var i=!0,s=n.props||L,c=n.ref,u=e.props,f=!F(c),d=e.children;if(f&&C(c.onComponentShouldUpdate)&&(i=c.onComponentShouldUpdate(u,s)),!1!==i){f&&C(c.onComponentWillUpdate)&&c.onComponentWillUpdate(u,s);var p=de(n.type(s,r));$e(d,p,t,r,l,o,a),n.children=p,f&&C(c.onComponentDidUpdate)&&c.onComponentDidUpdate(u,s)}else n.children=d}(e,n,t,r,l,o,a):16&$?(g=e,y=(m=n).children,k=g.dom,y!==g.children&&(k.nodeValue=y),m.dom=k):512&$?n.dom=e.dom:8192&$?function(e,n,t,r,l,o){var a=e.children,i=n.children,s=e.childFlags,c=n.childFlags,u=null;12&c&&0===i.length&&(c=n.childFlags=2,i=n.children=B());var f=0!=(2&c);if(12&s){var d=a.length;(8&s&&8&c||f||!f&&i.length>d)&&(u=U(a[d-1],!1).nextSibling)}be(s,c,a,i,t,r,l,u,e,o)}(e,n,t,r,l,a):function(e,n,t,r){var l=e.ref,o=n.ref,a=n.children;if(be(e.childFlags,n.childFlags,e.children,a,l,t,!1,null,e,r),n.dom=e.dom,l!==o&&!b(a)){var i=a.dom;x(l,i),N(o,i)}}(e,n,r,a)}function be(e,n,t,r,l,o,a,i,s,c){switch(e){case 2:switch(n){case 2:$e(t,r,l,o,a,i,c);break;case 1:re(t,l);break;case 16:le(t),he(l,r);break;default:g=r,m=l,y=o,k=a,$=c,le(h=t),me(g,m,y,k,U(h,!0),$),S(h,m)}break;case 1:switch(n){case 2:pe(r,l,o,a,i,c);break;case 1:break;case 16:he(l,r);break;default:me(r,l,o,a,i,c)}break;case 16:switch(n){case 16:v=l,(d=t)!==(p=r)&&(""!==d?v.firstChild.nodeValue=p:v.textContent=p);break;case 2:ae(l),pe(r,l,o,a,i,c);break;case 1:ae(l);break;default:ae(l),me(r,l,o,a,i,c)}break;default:switch(n){case 16:oe(t),he(l,r);break;case 2:ie(l,s,t),pe(r,l,o,a,i,c);break;case 1:ie(l,s,t);break;default:var u=0|t.length,f=0|r.length;0===u?0<f&&me(r,l,o,a,i,c):0===f?ie(l,s,t):8===n&&8===e?function(e,n,t,r,l,o,a,i,s,c){var u,f,d=o-1,p=a-1,v=0,h=0,g=e[h],m=n[h];e:{for(;g.key===m.key;){if(16384&m.flags&&(n[h]=m=M(m)),$e(g,m,t,r,l,i,c),e[h]=m,d<++h||p<h)break e;g=e[h],m=n[h]}for(g=e[d],m=n[p];g.key===m.key;){if(16384&m.flags&&(n[p]=m=M(m)),$e(g,m,t,r,l,i,c),e[d]=m,p--,--d<h||p<h)break e;g=e[d],m=n[p]}}if(d<h){if(h<=p)for(f=(u=p+1)<a?U(n[u],!0):i;h<=p;)16384&(m=n[h]).flags&&(n[h]=m=M(m)),++h,pe(m,t,r,l,f,c)}else if(p<h)for(;h<=d;)re(e[h++],t);else{for(var y=h,k=h,$=d-h+1,b=p-h+1,C=[];v++<=b;)C.push(0);var F=$===o,w=!1,P=0,N=0;if(a<4||($|b)<32)for(v=y;v<=d;++v)if(g=e[v],N<b){for(h=k;h<=p;h++)if(m=n[h],g.key===m.key){if(C[h-k]=v+1,F)for(F=!1;y<v;)re(e[y++],t);h<P?w=!0:P=h,16384&m.flags&&(n[h]=m=M(m)),$e(g,m,t,r,l,i,c),++N;break}!F&&p<h&&re(g,t)}else F||re(g,t);else{var x={};for(v=k;v<=p;++v)x[n[v].key]=v;for(v=y;v<=d;++v)if(g=e[v],N<b)if(void 0!==(h=x[g.key])){if(F)for(F=!1;y<v;)re(e[y++],t);m=n[h],C[h-k]=v+1,h<P?w=!0:P=h,16384&m.flags&&(n[h]=m=M(m)),$e(g,m,t,r,l,i,c),++N}else F||re(g,t);else F||re(g,t)}if(F)ie(t,s,e),me(n,t,r,l,i,c);else if(w){var S=function(e){var n,t,r,l,o,a=e.slice(),i=[0],s=e.length;for(n=0;n<s;++n){var c=e[n];if(0!==c){if(e[t=i[i.length-1]]<c){a[n]=t,i.push(n);continue}for(r=0,l=i.length-1;r<l;)e[i[o=(r+l)/2|0]]<c?r=o+1:l=o;c<e[i[r]]&&(0<r&&(a[n]=i[r-1]),i[r]=n)}}for(l=i[(r=i.length)-1];0<r--;)l=a[i[r]=l];return i}(C);for(h=S.length-1,v=b-1;0<=v;v--)0===C[v]?(16384&(m=n[P=v+k]).flags&&(n[P]=m=M(m)),pe(m,t,r,l,(u=P+1)<a?U(n[u],!0):i,c)):h<0||v!==S[h]?V(m=n[P=v+k],t,(u=P+1)<a?U(n[u],!0):i):h--}else if(N!==b)for(v=b-1;0<=v;v--)0===C[v]&&(16384&(m=n[P=v+k]).flags&&(n[P]=m=M(m)),pe(m,t,r,l,(u=P+1)<a?U(n[u],!0):i,c))}}(t,r,l,o,a,u,f,i,s,c):function(e,n,t,r,l,o,a,i,s){for(var c,u,f=a<o?a:o,d=0;d<f;++d)c=n[d],u=e[d],16384&c.flags&&(c=n[d]=M(c)),$e(u,c,t,r,l,i,s),e[d]=c;if(o<a)for(d=f;d<a;++d)16384&(c=n[d]).flags&&(c=n[d]=M(c)),pe(c,t,r,l,i,s);else if(a<o)for(d=f;d<o;++d)re(e[d],t)}(t,r,l,o,a,u,f,i,c)}}var d,p,v,h,g,m,y,k,$}function Ce(e,n,t,r,l,o,a,i,s){var c,u,f,d,p=e.state,v=e.props,h=Boolean(e.$N),g=C(e.shouldComponentUpdate);if(h&&(n=k(e,t,n!==p?P(p,n):n)),a||!g||g&&e.shouldComponentUpdate(t,n,l)){!h&&C(e.componentWillUpdate)&&e.componentWillUpdate(t,n,l),e.props=t,e.state=n,e.context=l;var m=null,y=ue(e,t,l);h&&C(e.getSnapshotBeforeUpdate)&&(m=e.getSnapshotBeforeUpdate(v,p)),$e(e.$LI,y,r,e.$CX,o,i,s),e.$LI=y,C(e.componentDidUpdate)&&(c=e,u=v,f=p,d=m,s.push(function(){c.componentDidUpdate(u,f,d)}))}else e.props=t,e.state=n,e.context=l}function o(e,n,t,r){var l=[],o=n.$V;i.v=!0,F(o)?F(e)||(16384&e.flags&&(e=M(e)),pe(e,n,r,!1,null,l),o=n.$V=e):F(e)?(re(o,n),n.$V=null):(16384&e.flags&&(e=M(e)),$e(o,e,n,r,!1,null,l),o=n.$V=e),0<l.length&&a(l),i.v=!1,C(t)&&t(),C(g.renderComplete)&&g.renderComplete(o,n)}function Fe(e,n,t,r){void 0===t&&(t=null),void 0===r&&(r=L),o(e,n,t,r)}"undefined"!=typeof document&&(document.body,Node.prototype.$EV=null,Node.prototype.$V=null);var we=[],Pe="undefined"!=typeof Promise?Promise.resolve().then.bind(Promise.resolve()):setTimeout.bind(window),Ne=!1;function xe(e,n,t,r){var l=e.$PS;if(C(n)&&(n=n(l?P(e.state,l):e.state,e.props,e.context)),F(l))e.$PS=n;else for(var o in n)l[o]=n[o];if(e.$BR)C(t)&&e.$L.push(t.bind(e));else{if(!i.v&&0===we.length)return void Ve(e,r,t);if(-1===we.indexOf(e)&&we.push(e),Ne||(Ne=!0,Pe(Ue)),C(t)){var a=e.$QU;a||(a=e.$QU=[]),a.push(t)}}}function Se(e){for(var n=e.$QU,t=0,r=n.length;t<r;++t)n[t].call(e);e.$QU=null}function Ue(){var e;for(Ne=!1;e=we.pop();)Ve(e,!1,e.$QU?Se.bind(null,e):null)}function Ve(e,n,t){if(!e.$UN){if(n||!e.$BR){var r=e.$PS;e.$PS=null;var l=[];i.v=!0,Ce(e,P(e.state,r),e.props,U(e.$LI,!0).parentNode,e.context,e.$SVG,n,null,l),0<l.length&&a(l),i.v=!1}else e.state=e.$PS,e.$PS=null;C(t)&&t.call(e)}}var Me=function(e,n){this.state=null,this.$BR=!1,this.$BS=!0,this.$PS=null,this.$LI=null,this.$UN=!1,this.$CX=null,this.$QU=null,this.$N=!1,this.$L=null,this.$SVG=!1,this.props=e||L,this.context=n||L};Me.prototype.forceUpdate=function(e){this.$UN||xe(this,{},e,!0)},Me.prototype.setState=function(e,n){this.$UN||this.$BS||xe(this,e,n,!1)},Me.prototype.render=function(e,n,t){return null},e.Component=Me,e.Fragment="$F",e.EMPTY_OBJ=L,e.createComponentVNode=function(e,n,t,r,l){0!=(2&e)&&(n.prototype&&n.prototype.render?e=4:n.render?(e=32776,n=n.render):e=8);var o=n.defaultProps;if(!F(o))for(var a in t||(t={}),o)v(t[a])&&(t[a]=o[a]);if(0<(8&e)&&0==(32768&e)){var i=n.defaultHooks;if(!F(i))if(l)for(var s in i)v(l[s])&&(l[s]=i[s]);else l=i}var c=new y(1,null,null,e,r,t,l,n),u=g.createVNode;return C(u)&&u(c),c},e.createFragment=s,e.createPortal=function(e,n){return l(1024,1024,null,e,0,null,b(e)?null:e.key,n)},e.createRef=function(){return{current:null}},e.createRenderer=function(l){return function(e,n,t,r){l||(l=e),Fe(n,l,t,r)}},e.createTextVNode=$,e.createVNode=l,e.forwardRef=function(e){return{render:e}},e.directClone=M,e.findDOMfromVNode=U,e.getFlagsForElementVnode=function(e){switch(e){case"svg":return 32;case"input":return 64;case"select":return 256;case"textarea":return 128;case"$F":return 8192;default:return 1}},e.linkEvent=function(e,n){return C(n)?{data:e,event:n}:null},e.normalizeProps=function(e){var n=e.props;if(n){var t=e.flags;481&t&&(void 0!==n.children&&F(e.children)&&_(e,n.children),void 0!==n.className&&(e.className=n.className||null,n.className=void 0)),void 0!==n.key&&(e.key=n.key,n.key=void 0),void 0!==n.ref&&(e.ref=8&t?P(e.ref,n.ref):n.ref,n.ref=void 0)}return e},e.options=g,e.render=Fe,e.rerender=Ue,e.version="7.0.2",e._CI=fe,e._HI=de,e._M=pe,e._MCCC=ye,e._ME=ge,e._MFCC=ke,e._MR=te,e._MT=ve,e._MP=ce,e.__render=o,Object.defineProperty(e,"__esModule",{value:!0})});

/** ../vendors/purify.min.js **/
!function(e,t){"object"==typeof exports&&"undefined"!=typeof module?module.exports=t():"function"==typeof define&&define.amd?define(t):e.DOMPurify=t()}(this,function(){"use strict";function e(e,t){for(var n=t.length;n--;)"string"==typeof t[n]&&(t[n]=t[n].toLowerCase()),e[t[n]]=!0;return e}function t(e){var t={},n=void 0;for(n in e)Object.prototype.hasOwnProperty.call(e,n)&&(t[n]=e[n]);return t}function n(e){if(Array.isArray(e)){for(var t=0,n=Array(e.length);t<e.length;t++)n[t]=e[t];return n}return Array.from(e)}function r(){var x=arguments.length>0&&void 0!==arguments[0]?arguments[0]:A(),S=function(e){return r(e)};if(S.version="1.0.8",S.removed=[],!x||!x.document||9!==x.document.nodeType)return S.isSupported=!1,S;var k=x.document,w=!1,L=!1,E=x.document,O=x.DocumentFragment,M=x.HTMLTemplateElement,N=x.Node,_=x.NodeFilter,D=x.NamedNodeMap,C=void 0===D?x.NamedNodeMap||x.MozNamedAttrMap:D,R=x.Text,F=x.Comment,z=x.DOMParser;if("function"==typeof M){var H=E.createElement("template");H.content&&H.content.ownerDocument&&(E=H.content.ownerDocument)}var I=E,j=I.implementation,P=I.createNodeIterator,U=I.getElementsByTagName,W=I.createDocumentFragment,B=k.importNode,G={};S.isSupported=j&&void 0!==j.createHTMLDocument&&9!==E.documentMode;var q=f,V=p,Y=h,K=g,X=v,$=b,J=y,Q=null,Z=e({},[].concat(n(o),n(i),n(a),n(l),n(s))),ee=null,te=e({},[].concat(n(c),n(d),n(u),n(m))),ne=null,re=null,oe=!0,ie=!0,ae=!1,le=!1,se=!1,ce=!1,de=!1,ue=!1,me=!1,fe=!1,pe=!1,he=!0,ge=!0,ye=!1,ve={},be=e({},["audio","head","math","script","style","template","svg","video"]),Te=e({},["audio","video","img","source","image"]),Ae=e({},["alt","class","for","id","label","name","pattern","placeholder","summary","title","value","style","xmlns"]),xe=null,Se=E.createElement("form"),ke=function(r){"object"!==(void 0===r?"undefined":T(r))&&(r={}),Q="ALLOWED_TAGS"in r?e({},r.ALLOWED_TAGS):Z,ee="ALLOWED_ATTR"in r?e({},r.ALLOWED_ATTR):te,ne="FORBID_TAGS"in r?e({},r.FORBID_TAGS):{},re="FORBID_ATTR"in r?e({},r.FORBID_ATTR):{},ve="USE_PROFILES"in r&&r.USE_PROFILES,oe=!1!==r.ALLOW_ARIA_ATTR,ie=!1!==r.ALLOW_DATA_ATTR,ae=r.ALLOW_UNKNOWN_PROTOCOLS||!1,le=r.SAFE_FOR_JQUERY||!1,se=r.SAFE_FOR_TEMPLATES||!1,ce=r.WHOLE_DOCUMENT||!1,me=r.RETURN_DOM||!1,fe=r.RETURN_DOM_FRAGMENT||!1,pe=r.RETURN_DOM_IMPORT||!1,ue=r.FORCE_BODY||!1,he=!1!==r.SANITIZE_DOM,ge=!1!==r.KEEP_CONTENT,ye=r.IN_PLACE||!1,J=r.ALLOWED_URI_REGEXP||J,se&&(ie=!1),fe&&(me=!0),ve&&(Q=e({},[].concat(n(s))),ee=[],!0===ve.html&&(e(Q,o),e(ee,c)),!0===ve.svg&&(e(Q,i),e(ee,d),e(ee,m)),!0===ve.svgFilters&&(e(Q,a),e(ee,d),e(ee,m)),!0===ve.mathMl&&(e(Q,l),e(ee,u),e(ee,m))),r.ADD_TAGS&&(Q===Z&&(Q=t(Q)),e(Q,r.ADD_TAGS)),r.ADD_ATTR&&(ee===te&&(ee=t(ee)),e(ee,r.ADD_ATTR)),r.ADD_URI_SAFE_ATTR&&e(Ae,r.ADD_URI_SAFE_ATTR),ge&&(Q["#text"]=!0),ce&&e(Q,["html","head","body"]),Q.table&&e(Q,["tbody"]),Object&&"freeze"in Object&&Object.freeze(r),xe=r},we=function(e){S.removed.push({element:e});try{e.parentNode.removeChild(e)}catch(t){e.outerHTML=""}},Le=function(e,t){try{S.removed.push({attribute:t.getAttributeNode(e),from:t})}catch(e){S.removed.push({attribute:null,from:t})}t.removeAttribute(e)},Ee=function(t){var n=void 0;if(ue&&(t="<remove></remove>"+t),w)try{n=(new z).parseFromString(t,"text/html")}catch(e){}if(L&&e(ne,["title"]),!n||!n.documentElement){var r=(n=j.createHTMLDocument("")).body;r.parentNode.removeChild(r.parentNode.firstElementChild),r.outerHTML=t}return U.call(n,ce?"html":"body")[0]};S.isSupported&&(function(){try{Ee('<svg><p><style><img src="</style><img src=x onerror=alert(1)//">').querySelector("svg img")&&(w=!0)}catch(e){}}(),function(){try{Ee("<x/><title>&lt;/title&gt;&lt;img&gt;").querySelector("title").textContent.match(/<\/title/)&&(L=!0)}catch(e){}}());var Oe=function(e){return P.call(e.ownerDocument||e,e,_.SHOW_ELEMENT|_.SHOW_COMMENT|_.SHOW_TEXT,function(){return _.FILTER_ACCEPT},!1)},Me=function(e){return!(e instanceof R||e instanceof F)&&!("string"==typeof e.nodeName&&"string"==typeof e.textContent&&"function"==typeof e.removeChild&&e.attributes instanceof C&&"function"==typeof e.removeAttribute&&"function"==typeof e.setAttribute)},Ne=function(e){return"object"===(void 0===N?"undefined":T(N))?e instanceof N:e&&"object"===(void 0===e?"undefined":T(e))&&"number"==typeof e.nodeType&&"string"==typeof e.nodeName},_e=function(e,t,n){G[e]&&G[e].forEach(function(e){e.call(S,t,n,xe)})},De=function(e){var t=void 0;if(_e("beforeSanitizeElements",e,null),Me(e))return we(e),!0;var n=e.nodeName.toLowerCase();if(_e("uponSanitizeElement",e,{tagName:n,allowedTags:Q}),!Q[n]||ne[n]){if(ge&&!be[n]&&"function"==typeof e.insertAdjacentHTML)try{e.insertAdjacentHTML("AfterEnd",e.innerHTML)}catch(e){}return we(e),!0}return!le||e.firstElementChild||e.content&&e.content.firstElementChild||!/</g.test(e.textContent)||(S.removed.push({element:e.cloneNode()}),e.innerHTML?e.innerHTML=e.innerHTML.replace(/</g,"&lt;"):e.innerHTML=e.textContent.replace(/</g,"&lt;")),se&&3===e.nodeType&&(t=(t=(t=e.textContent).replace(q," ")).replace(V," "),e.textContent!==t&&(S.removed.push({element:e.cloneNode()}),e.textContent=t)),_e("afterSanitizeElements",e,null),!1},Ce=function(e,t,n){if(he&&("id"===t||"name"===t)&&(n in E||n in Se))return!1;if(se&&(n=(n=n.replace(q," ")).replace(V," ")),ie&&Y.test(t));else if(oe&&K.test(t));else{if(!ee[t]||re[t])return!1;if(Ae[t]);else if(J.test(n.replace($,"")));else if("src"!==t&&"xlink:href"!==t||"script"===e||0!==n.indexOf("data:")||!Te[e]){if(ae&&!X.test(n.replace($,"")));else if(n)return!1}else;}return!0},Re=function(e){var t=void 0,n=void 0,r=void 0,o=void 0,i=void 0;_e("beforeSanitizeAttributes",e,null);var a=e.attributes;if(a){var l={attrName:"",attrValue:"",keepAttr:!0,allowedAttributes:ee};for(i=a.length;i--;){var s=t=a[i],c=s.name,d=s.namespaceURI;if(n=t.value.trim(),r=c.toLowerCase(),l.attrName=r,l.attrValue=n,l.keepAttr=!0,_e("uponSanitizeAttribute",e,l),n=l.attrValue,"name"===r&&"IMG"===e.nodeName&&a.id)o=a.id,a=Array.prototype.slice.apply(a),Le("id",e),Le(c,e),a.indexOf(o)>i&&e.setAttribute("id",o.value);else{if("INPUT"===e.nodeName&&"type"===r&&"file"===n&&(ee[r]||!re[r]))continue;"id"===c&&e.setAttribute(c,""),Le(c,e)}if(l.keepAttr){var u=e.nodeName.toLowerCase();if(Ce(u,r,n))try{d?e.setAttributeNS(d,c,n):e.setAttribute(c,n),S.removed.pop()}catch(e){}}}_e("afterSanitizeAttributes",e,null)}},Fe=function e(t){var n=void 0,r=Oe(t);for(_e("beforeSanitizeShadowDOM",t,null);n=r.nextNode();)_e("uponSanitizeShadowNode",n,null),De(n)||(n.content instanceof O&&e(n.content),Re(n));_e("afterSanitizeShadowDOM",t,null)};return S.sanitize=function(e,t){var n=void 0,r=void 0,o=void 0,i=void 0,a=void 0;if(e||(e="\x3c!--\x3e"),"string"!=typeof e&&!Ne(e)){if("function"!=typeof e.toString)throw new TypeError("toString is not a function");if("string"!=typeof(e=e.toString()))throw new TypeError("dirty is not a string, aborting")}if(!S.isSupported){if("object"===T(x.toStaticHTML)||"function"==typeof x.toStaticHTML){if("string"==typeof e)return x.toStaticHTML(e);if(Ne(e))return x.toStaticHTML(e.outerHTML)}return e}if(de||ke(t),S.removed=[],ye);else if(e instanceof N)1===(r=(n=Ee("\x3c!--\x3e")).ownerDocument.importNode(e,!0)).nodeType&&"BODY"===r.nodeName?n=r:n.appendChild(r);else{if(!me&&!ce&&-1===e.indexOf("<"))return e;if(!(n=Ee(e)))return me?null:""}n&&ue&&we(n.firstChild);for(var l=Oe(ye?e:n);o=l.nextNode();)3===o.nodeType&&o===i||De(o)||(o.content instanceof O&&Fe(o.content),Re(o),i=o);if(ye)return e;if(me){if(fe)for(a=W.call(n.ownerDocument);n.firstChild;)a.appendChild(n.firstChild);else a=n;return pe&&(a=B.call(k,a,!0)),a}return ce?n.outerHTML:n.innerHTML},S.setConfig=function(e){ke(e),de=!0},S.clearConfig=function(){xe=null,de=!1},S.isValidAttribute=function(e,t,n){xe||ke({});var r=e.toLowerCase(),o=t.toLowerCase();return Ce(r,o,n)},S.addHook=function(e,t){"function"==typeof t&&(G[e]=G[e]||[],G[e].push(t))},S.removeHook=function(e){G[e]&&G[e].pop()},S.removeHooks=function(e){G[e]&&(G[e]=[])},S.removeAllHooks=function(){G={}},S}var o=["a","abbr","acronym","address","area","article","aside","audio","b","bdi","bdo","big","blink","blockquote","body","br","button","canvas","caption","center","cite","code","col","colgroup","content","data","datalist","dd","decorator","del","details","dfn","dir","div","dl","dt","element","em","fieldset","figcaption","figure","font","footer","form","h1","h2","h3","h4","h5","h6","head","header","hgroup","hr","html","i","img","input","ins","kbd","label","legend","li","main","map","mark","marquee","menu","menuitem","meter","nav","nobr","ol","optgroup","option","output","p","pre","progress","q","rp","rt","ruby","s","samp","section","select","shadow","small","source","spacer","span","strike","strong","style","sub","summary","sup","table","tbody","td","template","textarea","tfoot","th","thead","time","tr","track","tt","u","ul","var","video","wbr"],i=["svg","a","altglyph","altglyphdef","altglyphitem","animatecolor","animatemotion","animatetransform","audio","canvas","circle","clippath","defs","desc","ellipse","filter","font","g","glyph","glyphref","hkern","image","line","lineargradient","marker","mask","metadata","mpath","path","pattern","polygon","polyline","radialgradient","rect","stop","style","switch","symbol","text","textpath","title","tref","tspan","video","view","vkern"],a=["feBlend","feColorMatrix","feComponentTransfer","feComposite","feConvolveMatrix","feDiffuseLighting","feDisplacementMap","feDistantLight","feFlood","feFuncA","feFuncB","feFuncG","feFuncR","feGaussianBlur","feMerge","feMergeNode","feMorphology","feOffset","fePointLight","feSpecularLighting","feSpotLight","feTile","feTurbulence"],l=["math","menclose","merror","mfenced","mfrac","mglyph","mi","mlabeledtr","mmuliscripts","mn","mo","mover","mpadded","mphantom","mroot","mrow","ms","mpspace","msqrt","mystyle","msub","msup","msubsup","mtable","mtd","mtext","mtr","munder","munderover"],s=["#text"],c=["accept","action","align","alt","autocomplete","background","bgcolor","border","cellpadding","cellspacing","checked","cite","class","clear","color","cols","colspan","coords","crossorigin","datetime","default","dir","disabled","download","enctype","face","for","headers","height","hidden","high","href","hreflang","id","integrity","ismap","label","lang","list","loop","low","max","maxlength","media","method","min","multiple","name","noshade","novalidate","nowrap","open","optimum","pattern","placeholder","poster","preload","pubdate","radiogroup","readonly","rel","required","rev","reversed","role","rows","rowspan","spellcheck","scope","selected","shape","size","sizes","span","srclang","start","src","srcset","step","style","summary","tabindex","title","type","usemap","valign","value","width","xmlns"],d=["accent-height","accumulate","additivive","alignment-baseline","ascent","attributename","attributetype","azimuth","basefrequency","baseline-shift","begin","bias","by","class","clip","clip-path","clip-rule","color","color-interpolation","color-interpolation-filters","color-profile","color-rendering","cx","cy","d","dx","dy","diffuseconstant","direction","display","divisor","dur","edgemode","elevation","end","fill","fill-opacity","fill-rule","filter","flood-color","flood-opacity","font-family","font-size","font-size-adjust","font-stretch","font-style","font-variant","font-weight","fx","fy","g1","g2","glyph-name","glyphref","gradientunits","gradienttransform","height","href","id","image-rendering","in","in2","k","k1","k2","k3","k4","kerning","keypoints","keysplines","keytimes","lang","lengthadjust","letter-spacing","kernelmatrix","kernelunitlength","lighting-color","local","marker-end","marker-mid","marker-start","markerheight","markerunits","markerwidth","maskcontentunits","maskunits","max","mask","media","method","mode","min","name","numoctaves","offset","operator","opacity","order","orient","orientation","origin","overflow","paint-order","path","pathlength","patterncontentunits","patterntransform","patternunits","points","preservealpha","preserveaspectratio","r","rx","ry","radius","refx","refy","repeatcount","repeatdur","restart","result","rotate","scale","seed","shape-rendering","specularconstant","specularexponent","spreadmethod","stddeviation","stitchtiles","stop-color","stop-opacity","stroke-dasharray","stroke-dashoffset","stroke-linecap","stroke-linejoin","stroke-miterlimit","stroke-opacity","stroke","stroke-width","style","surfacescale","tabindex","targetx","targety","transform","text-anchor","text-decoration","text-rendering","textlength","type","u1","u2","unicode","values","viewbox","visibility","vert-adv-y","vert-origin-x","vert-origin-y","width","word-spacing","wrap","writing-mode","xchannelselector","ychannelselector","x","x1","x2","xmlns","y","y1","y2","z","zoomandpan"],u=["accent","accentunder","align","bevelled","close","columnsalign","columnlines","columnspan","denomalign","depth","dir","display","displaystyle","fence","frame","height","href","id","largeop","length","linethickness","lspace","lquote","mathbackground","mathcolor","mathsize","mathvariant","maxsize","minsize","movablelimits","notation","numalign","open","rowalign","rowlines","rowspacing","rowspan","rspace","rquote","scriptlevel","scriptminsize","scriptsizemultiplier","selection","separator","separators","stretchy","subscriptshift","supscriptshift","symmetric","voffset","width","xmlns"],m=["xlink:href","xml:id","xlink:title","xml:space","xmlns:xlink"],f=/\{\{[\s\S]*|[\s\S]*\}\}/gm,p=/<%[\s\S]*|[\s\S]*%>/gm,h=/^data-[\-\w.\u00B7-\uFFFF]/,g=/^aria-[\-\w]+$/,y=/^(?:(?:(?:f|ht)tps?|mailto|tel|callto|cid|xmpp):|[^a-z]|[a-z+.\-]+(?:[^a-z+.\-:]|$))/i,v=/^(?:\w+script|data):/i,b=/[\u0000-\u0020\u00A0\u1680\u180E\u2000-\u2029\u205f\u3000]/g,T="function"==typeof Symbol&&"symbol"==typeof Symbol.iterator?function(e){return typeof e}:function(e){return e&&"function"==typeof Symbol&&e.constructor===Symbol&&e!==Symbol.prototype?"symbol":typeof e},A=function(){return"undefined"==typeof window?null:window};return r()});
//# sourceMappingURL=purify.min.js.map

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

/** ..\Modules\cryptohash\md5.js **/
/*
CryptoJS v3.1.2
code.google.com/p/crypto-js
(c) 2009-2013 by Jeff Mott. All rights reserved.
code.google.com/p/crypto-js/wiki/License
*/
(function (Math) {
    // Shortcuts
    var C = CryptoJS;
    var C_lib = C.lib;
    var WordArray = C_lib.WordArray;
    var Hasher = C_lib.Hasher;
    var C_algo = C.algo;

    // Constants table
    var T = [];

    // Compute constants
    (function () {
        for (var i = 0; i < 64; i++) {
            T[i] = (Math.abs(Math.sin(i + 1)) * 0x100000000) | 0;
        }
    }());

    /**
     * MD5 hash algorithm.
     */
    var MD5 = C_algo.MD5 = Hasher.extend({
        _doReset: function () {
            this._hash = new WordArray.init([
                0x67452301, 0xefcdab89,
                0x98badcfe, 0x10325476
            ]);
        },

        _doProcessBlock: function (M, offset) {
            // Swap endian
            for (var i = 0; i < 16; i++) {
                // Shortcuts
                var offset_i = offset + i;
                var M_offset_i = M[offset_i];

                M[offset_i] = (
                    (((M_offset_i << 8)  | (M_offset_i >>> 24)) & 0x00ff00ff) |
                    (((M_offset_i << 24) | (M_offset_i >>> 8))  & 0xff00ff00)
                );
            }

            // Shortcuts
            var H = this._hash.words;

            var M_offset_0  = M[offset + 0];
            var M_offset_1  = M[offset + 1];
            var M_offset_2  = M[offset + 2];
            var M_offset_3  = M[offset + 3];
            var M_offset_4  = M[offset + 4];
            var M_offset_5  = M[offset + 5];
            var M_offset_6  = M[offset + 6];
            var M_offset_7  = M[offset + 7];
            var M_offset_8  = M[offset + 8];
            var M_offset_9  = M[offset + 9];
            var M_offset_10 = M[offset + 10];
            var M_offset_11 = M[offset + 11];
            var M_offset_12 = M[offset + 12];
            var M_offset_13 = M[offset + 13];
            var M_offset_14 = M[offset + 14];
            var M_offset_15 = M[offset + 15];

            // Working varialbes
            var a = H[0];
            var b = H[1];
            var c = H[2];
            var d = H[3];

            // Computation
            a = FF(a, b, c, d, M_offset_0,  7,  T[0]);
            d = FF(d, a, b, c, M_offset_1,  12, T[1]);
            c = FF(c, d, a, b, M_offset_2,  17, T[2]);
            b = FF(b, c, d, a, M_offset_3,  22, T[3]);
            a = FF(a, b, c, d, M_offset_4,  7,  T[4]);
            d = FF(d, a, b, c, M_offset_5,  12, T[5]);
            c = FF(c, d, a, b, M_offset_6,  17, T[6]);
            b = FF(b, c, d, a, M_offset_7,  22, T[7]);
            a = FF(a, b, c, d, M_offset_8,  7,  T[8]);
            d = FF(d, a, b, c, M_offset_9,  12, T[9]);
            c = FF(c, d, a, b, M_offset_10, 17, T[10]);
            b = FF(b, c, d, a, M_offset_11, 22, T[11]);
            a = FF(a, b, c, d, M_offset_12, 7,  T[12]);
            d = FF(d, a, b, c, M_offset_13, 12, T[13]);
            c = FF(c, d, a, b, M_offset_14, 17, T[14]);
            b = FF(b, c, d, a, M_offset_15, 22, T[15]);

            a = GG(a, b, c, d, M_offset_1,  5,  T[16]);
            d = GG(d, a, b, c, M_offset_6,  9,  T[17]);
            c = GG(c, d, a, b, M_offset_11, 14, T[18]);
            b = GG(b, c, d, a, M_offset_0,  20, T[19]);
            a = GG(a, b, c, d, M_offset_5,  5,  T[20]);
            d = GG(d, a, b, c, M_offset_10, 9,  T[21]);
            c = GG(c, d, a, b, M_offset_15, 14, T[22]);
            b = GG(b, c, d, a, M_offset_4,  20, T[23]);
            a = GG(a, b, c, d, M_offset_9,  5,  T[24]);
            d = GG(d, a, b, c, M_offset_14, 9,  T[25]);
            c = GG(c, d, a, b, M_offset_3,  14, T[26]);
            b = GG(b, c, d, a, M_offset_8,  20, T[27]);
            a = GG(a, b, c, d, M_offset_13, 5,  T[28]);
            d = GG(d, a, b, c, M_offset_2,  9,  T[29]);
            c = GG(c, d, a, b, M_offset_7,  14, T[30]);
            b = GG(b, c, d, a, M_offset_12, 20, T[31]);

            a = HH(a, b, c, d, M_offset_5,  4,  T[32]);
            d = HH(d, a, b, c, M_offset_8,  11, T[33]);
            c = HH(c, d, a, b, M_offset_11, 16, T[34]);
            b = HH(b, c, d, a, M_offset_14, 23, T[35]);
            a = HH(a, b, c, d, M_offset_1,  4,  T[36]);
            d = HH(d, a, b, c, M_offset_4,  11, T[37]);
            c = HH(c, d, a, b, M_offset_7,  16, T[38]);
            b = HH(b, c, d, a, M_offset_10, 23, T[39]);
            a = HH(a, b, c, d, M_offset_13, 4,  T[40]);
            d = HH(d, a, b, c, M_offset_0,  11, T[41]);
            c = HH(c, d, a, b, M_offset_3,  16, T[42]);
            b = HH(b, c, d, a, M_offset_6,  23, T[43]);
            a = HH(a, b, c, d, M_offset_9,  4,  T[44]);
            d = HH(d, a, b, c, M_offset_12, 11, T[45]);
            c = HH(c, d, a, b, M_offset_15, 16, T[46]);
            b = HH(b, c, d, a, M_offset_2,  23, T[47]);

            a = II(a, b, c, d, M_offset_0,  6,  T[48]);
            d = II(d, a, b, c, M_offset_7,  10, T[49]);
            c = II(c, d, a, b, M_offset_14, 15, T[50]);
            b = II(b, c, d, a, M_offset_5,  21, T[51]);
            a = II(a, b, c, d, M_offset_12, 6,  T[52]);
            d = II(d, a, b, c, M_offset_3,  10, T[53]);
            c = II(c, d, a, b, M_offset_10, 15, T[54]);
            b = II(b, c, d, a, M_offset_1,  21, T[55]);
            a = II(a, b, c, d, M_offset_8,  6,  T[56]);
            d = II(d, a, b, c, M_offset_15, 10, T[57]);
            c = II(c, d, a, b, M_offset_6,  15, T[58]);
            b = II(b, c, d, a, M_offset_13, 21, T[59]);
            a = II(a, b, c, d, M_offset_4,  6,  T[60]);
            d = II(d, a, b, c, M_offset_11, 10, T[61]);
            c = II(c, d, a, b, M_offset_2,  15, T[62]);
            b = II(b, c, d, a, M_offset_9,  21, T[63]);

            // Intermediate hash value
            H[0] = (H[0] + a) | 0;
            H[1] = (H[1] + b) | 0;
            H[2] = (H[2] + c) | 0;
            H[3] = (H[3] + d) | 0;
        },

        _doFinalize: function () {
            // Shortcuts
            var data = this._data;
            var dataWords = data.words;

            var nBitsTotal = this._nDataBytes * 8;
            var nBitsLeft = data.sigBytes * 8;

            // Add padding
            dataWords[nBitsLeft >>> 5] |= 0x80 << (24 - nBitsLeft % 32);

            var nBitsTotalH = Math.floor(nBitsTotal / 0x100000000);
            var nBitsTotalL = nBitsTotal;
            dataWords[(((nBitsLeft + 64) >>> 9) << 4) + 15] = (
                (((nBitsTotalH << 8)  | (nBitsTotalH >>> 24)) & 0x00ff00ff) |
                (((nBitsTotalH << 24) | (nBitsTotalH >>> 8))  & 0xff00ff00)
            );
            dataWords[(((nBitsLeft + 64) >>> 9) << 4) + 14] = (
                (((nBitsTotalL << 8)  | (nBitsTotalL >>> 24)) & 0x00ff00ff) |
                (((nBitsTotalL << 24) | (nBitsTotalL >>> 8))  & 0xff00ff00)
            );

            data.sigBytes = (dataWords.length + 1) * 4;

            // Hash final blocks
            this._process();

            // Shortcuts
            var hash = this._hash;
            var H = hash.words;

            // Swap endian
            for (var i = 0; i < 4; i++) {
                // Shortcut
                var H_i = H[i];

                H[i] = (((H_i << 8)  | (H_i >>> 24)) & 0x00ff00ff) |
                       (((H_i << 24) | (H_i >>> 8))  & 0xff00ff00);
            }

            // Return final computed hash
            return hash;
        },

        clone: function () {
            var clone = Hasher.clone.call(this);
            clone._hash = this._hash.clone();

            return clone;
        }
    });

    function FF(a, b, c, d, x, s, t) {
        var n = a + ((b & c) | (~b & d)) + x + t;
        return ((n << s) | (n >>> (32 - s))) + b;
    }

    function GG(a, b, c, d, x, s, t) {
        var n = a + ((b & d) | (c & ~d)) + x + t;
        return ((n << s) | (n >>> (32 - s))) + b;
    }

    function HH(a, b, c, d, x, s, t) {
        var n = a + (b ^ c ^ d) + x + t;
        return ((n << s) | (n >>> (32 - s))) + b;
    }

    function II(a, b, c, d, x, s, t) {
        var n = a + (c ^ (b | ~d)) + x + t;
        return ((n << s) | (n >>> (32 - s))) + b;
    }

    /**
     * Shortcut function to the hasher's object interface.
     *
     * @param {WordArray|string} message The message to hash.
     *
     * @return {WordArray} The hash.
     *
     * @static
     *
     * @example
     *
     *     var hash = CryptoJS.MD5('message');
     *     var hash = CryptoJS.MD5(wordArray);
     */
    C.MD5 = Hasher._createHelper(MD5);

    /**
     * Shortcut function to the HMAC's object interface.
     *
     * @param {WordArray|string} message The message to hash.
     * @param {WordArray|string} key The secret key.
     *
     * @return {WordArray} The HMAC.
     *
     * @static
     *
     * @example
     *
     *     var hmac = CryptoJS.HmacMD5(message, key);
     */
    C.HmacMD5 = Hasher._createHmacHelper(MD5);
}(Math));

/** ..\Modules\cryptohash\cryptohash.js **/
(function(externalParent) {
	var cryptohash = {};

	function hex(buffer) {
		var hexCodes = [];
		var view = new DataView(buffer);
		for (var i = 0; i < view.byteLength; i += 4) {
			// Using getUint32 reduces the number of iterations needed (we process 4 bytes each time)
			var value = view.getUint32(i);
			// toString(16) will give the hex representation of the number without padding
			var stringValue = value.toString(16);
			// We use concatenation and slice for padding
			var padding = '00000000';
			var paddedValue = (padding + stringValue).slice(-padding.length);
			hexCodes.push(paddedValue);
		}

		// Join all the hex strings into one
		return hexCodes.join('');
	}

	function stringToArrayBuffer(str) {
		return new Uint8Array(str.split('').map(function(sym) {
			return sym.charCodeAt();
		}));
	}

	cryptohash.SHA256 = function(str) {
		var buffer;
		if (typeof window.crypto !== 'undefined' && crypto.subtle && (!aras.Browser.isCh() || window.protocol === 'https:')) {
			if (window.TextEncoder) {
				buffer = new TextEncoder('utf-8').encode(str);
			} else {
				buffer = stringToArrayBuffer(str);
			}

			return crypto.subtle.digest('SHA-256', buffer).then(function(hash) {
				return hex(hash);
			});
		} else if (typeof window.msCrypto !== 'undefined') {
			buffer = stringToArrayBuffer(str);
			var sha256 = msCrypto.subtle.digest('SHA-256', buffer);
			return new Promise(function(resolve, reject) {
				sha256.oncomplete = function(event) {
					resolve(hex(event.target.result));
				};
			});
		} else {
			return Promise.resolve(CryptoJS.SHA256(str).toString(CryptoJS.enc.Hex));
		}
	};

	cryptohash.MD5 = function(message, config) {
		return CryptoJS.MD5(message, config);
	};

	cryptohash.xxHash = function() {
		throw new Exception('Cryptohash.xxHash not implemented');
	};

	externalParent.cryptohash = cryptohash;

	window.ArasModules = window.ArasModules || externalParent;
})(window.ArasModules || {});


/** ItemsGridAsyncSoap.js **/
function ItemsGridAsyncSoap(asyncController, itemId, requestId, customCallback) {
	this._itemId = itemId;
	this._requestId = requestId;
	this._asyncController = asyncController;
	this._customCallback = customCallback;
	var browser = this._asyncController.aras.Browser;
	this.soapController = browser.isIe() && browser.getMajorVersionNumber() < 10 ? undefined : new SoapController(this.commonCallback.bind(this));
}

ItemsGridAsyncSoap.prototype.commonCallback = function ItemsGridAsyncSoapCommonCallback(response) {
	var callbackArgument;
	try {
		if (this._customCallback) {
			callbackArgument = response.results.selectNodes('.//Result/Item');
			this._customCallback(callbackArgument);
		}
	} finally {
		this._asyncController.removeSoaps(function(inItemId, inRequestId) {
			return (inItemId === this._itemId && inRequestId === this._requestId);
		}.bind(this));
	}
};

/** ItemsGridAsyncController.js **/
function ItemsGridAsyncController(arasObj, windowObj) {
	this.aras = arasObj;
	this._soaps = {};	//collection of soap wrapper controllers, saved by itemId
	(windowObj || window).addEventListener('unload', this.abortRequests.bind(this, null));
}

ItemsGridAsyncController.prototype = {
	_getSoap: function ItemsGridAsyncControllerGetSoap(itemId, requestId) {
		return (this._soaps[itemId] && this._soaps[itemId][requestId]) || null;
	},

	_addSoap: function ItemsGridAsyncControllerAddSoap(itemId, requestId, customCallback) {
		var soap = new ItemsGridAsyncSoap(this, itemId, requestId, customCallback);
		this._soaps[itemId] = this._soaps[itemId] || {};
		this._soaps[itemId][requestId] = soap;
		return soap;
	},

	removeSoaps: function ItemsGridAsyncControllerRemoveSoaps(removeFilter) {
		var itemId;
		var itemSoaps;
		var requestId;
		var doRemove;
		for (itemId in this._soaps) {
			itemSoaps = this._soaps[itemId];
			for (requestId in itemSoaps) {
				doRemove = !removeFilter || removeFilter(itemId, requestId);
				if (doRemove) {
					delete itemSoaps[requestId];
				}
			}
		}
	},

	sendRequest: function ItemsGridAsyncControllerSendRequest(itemId, requestId, soapBody, customCallback) {
		var abortAndRemoveFilter = function(tmpItemId) {
			return (itemId !== tmpItemId);
		};
		var soap;
		var syncRequestResult;
		this.abortRequests(abortAndRemoveFilter);
		this.removeSoaps(abortAndRemoveFilter);

		soap = this._getSoap(itemId, requestId);
		if (!soap) {//soap is not sent yet, so, let's send it immediately!
			soap = this._addSoap(itemId, requestId, customCallback);

			syncRequestResult = this.aras.soapSend('GetItem', soapBody, '', false, soap.soapController);

			if (!soap.soapController) {
				soap.commonCallback(syncRequestResult);
			}
		}
	},

	abortRequests: function ItemsGridAsyncControllerAbortRequests(soapFilter) {
		var itemId;
		var requestId;
		var itemSoaps;
		var itemSoapController;
		var doStop;
		for (itemId in this._soaps) {
			itemSoaps = this._soaps[itemId];
			for (requestId in itemSoaps) {
				itemSoapController = itemSoaps[requestId].soapController;
				doStop = !soapFilter || soapFilter(itemId, requestId);
				if (itemSoapController && doStop && 'function' === typeof itemSoapController.stop) {
					itemSoapController.stop();
				}
			}
		}
	}
};

/** ../vendors/BigInteger.min.js **/
var bigInt=function(undefined){"use strict";var BASE=1e7,LOG_BASE=7,MAX_INT=9007199254740992,MAX_INT_ARR=smallToArray(MAX_INT),LOG_MAX_INT=Math.log(MAX_INT);function Integer(v,radix){if(typeof v==="undefined")return Integer[0];if(typeof radix!=="undefined")return+radix===10?parseValue(v):parseBase(v,radix);return parseValue(v)}function BigInteger(value,sign){this.value=value;this.sign=sign;this.isSmall=false}BigInteger.prototype=Object.create(Integer.prototype);function SmallInteger(value){this.value=value;this.sign=value<0;this.isSmall=true}SmallInteger.prototype=Object.create(Integer.prototype);function isPrecise(n){return-MAX_INT<n&&n<MAX_INT}function smallToArray(n){if(n<1e7)return[n];if(n<1e14)return[n%1e7,Math.floor(n/1e7)];return[n%1e7,Math.floor(n/1e7)%1e7,Math.floor(n/1e14)]}function arrayToSmall(arr){trim(arr);var length=arr.length;if(length<4&&compareAbs(arr,MAX_INT_ARR)<0){switch(length){case 0:return 0;case 1:return arr[0];case 2:return arr[0]+arr[1]*BASE;default:return arr[0]+(arr[1]+arr[2]*BASE)*BASE}}return arr}function trim(v){var i=v.length;while(v[--i]===0);v.length=i+1}function createArray(length){var x=new Array(length);var i=-1;while(++i<length){x[i]=0}return x}function truncate(n){if(n>0)return Math.floor(n);return Math.ceil(n)}function add(a,b){var l_a=a.length,l_b=b.length,r=new Array(l_a),carry=0,base=BASE,sum,i;for(i=0;i<l_b;i++){sum=a[i]+b[i]+carry;carry=sum>=base?1:0;r[i]=sum-carry*base}while(i<l_a){sum=a[i]+carry;carry=sum===base?1:0;r[i++]=sum-carry*base}if(carry>0)r.push(carry);return r}function addAny(a,b){if(a.length>=b.length)return add(a,b);return add(b,a)}function addSmall(a,carry){var l=a.length,r=new Array(l),base=BASE,sum,i;for(i=0;i<l;i++){sum=a[i]-base+carry;carry=Math.floor(sum/base);r[i]=sum-carry*base;carry+=1}while(carry>0){r[i++]=carry%base;carry=Math.floor(carry/base)}return r}BigInteger.prototype.add=function(v){var n=parseValue(v);if(this.sign!==n.sign){return this.subtract(n.negate())}var a=this.value,b=n.value;if(n.isSmall){return new BigInteger(addSmall(a,Math.abs(b)),this.sign)}return new BigInteger(addAny(a,b),this.sign)};BigInteger.prototype.plus=BigInteger.prototype.add;SmallInteger.prototype.add=function(v){var n=parseValue(v);var a=this.value;if(a<0!==n.sign){return this.subtract(n.negate())}var b=n.value;if(n.isSmall){if(isPrecise(a+b))return new SmallInteger(a+b);b=smallToArray(Math.abs(b))}return new BigInteger(addSmall(b,Math.abs(a)),a<0)};SmallInteger.prototype.plus=SmallInteger.prototype.add;function subtract(a,b){var a_l=a.length,b_l=b.length,r=new Array(a_l),borrow=0,base=BASE,i,difference;for(i=0;i<b_l;i++){difference=a[i]-borrow-b[i];if(difference<0){difference+=base;borrow=1}else borrow=0;r[i]=difference}for(i=b_l;i<a_l;i++){difference=a[i]-borrow;if(difference<0)difference+=base;else{r[i++]=difference;break}r[i]=difference}for(;i<a_l;i++){r[i]=a[i]}trim(r);return r}function subtractAny(a,b,sign){var value;if(compareAbs(a,b)>=0){value=subtract(a,b)}else{value=subtract(b,a);sign=!sign}value=arrayToSmall(value);if(typeof value==="number"){if(sign)value=-value;return new SmallInteger(value)}return new BigInteger(value,sign)}function subtractSmall(a,b,sign){var l=a.length,r=new Array(l),carry=-b,base=BASE,i,difference;for(i=0;i<l;i++){difference=a[i]+carry;carry=Math.floor(difference/base);difference%=base;r[i]=difference<0?difference+base:difference}r=arrayToSmall(r);if(typeof r==="number"){if(sign)r=-r;return new SmallInteger(r)}return new BigInteger(r,sign)}BigInteger.prototype.subtract=function(v){var n=parseValue(v);if(this.sign!==n.sign){return this.add(n.negate())}var a=this.value,b=n.value;if(n.isSmall)return subtractSmall(a,Math.abs(b),this.sign);return subtractAny(a,b,this.sign)};BigInteger.prototype.minus=BigInteger.prototype.subtract;SmallInteger.prototype.subtract=function(v){var n=parseValue(v);var a=this.value;if(a<0!==n.sign){return this.add(n.negate())}var b=n.value;if(n.isSmall){return new SmallInteger(a-b)}return subtractSmall(b,Math.abs(a),a>=0)};SmallInteger.prototype.minus=SmallInteger.prototype.subtract;BigInteger.prototype.negate=function(){return new BigInteger(this.value,!this.sign)};SmallInteger.prototype.negate=function(){var sign=this.sign;var small=new SmallInteger(-this.value);small.sign=!sign;return small};BigInteger.prototype.abs=function(){return new BigInteger(this.value,false)};SmallInteger.prototype.abs=function(){return new SmallInteger(Math.abs(this.value))};function multiplyLong(a,b){var a_l=a.length,b_l=b.length,l=a_l+b_l,r=createArray(l),base=BASE,product,carry,i,a_i,b_j;for(i=0;i<a_l;++i){a_i=a[i];for(var j=0;j<b_l;++j){b_j=b[j];product=a_i*b_j+r[i+j];carry=Math.floor(product/base);r[i+j]=product-carry*base;r[i+j+1]+=carry}}trim(r);return r}function multiplySmall(a,b){var l=a.length,r=new Array(l),base=BASE,carry=0,product,i;for(i=0;i<l;i++){product=a[i]*b+carry;carry=Math.floor(product/base);r[i]=product-carry*base}while(carry>0){r[i++]=carry%base;carry=Math.floor(carry/base)}return r}function shiftLeft(x,n){var r=[];while(n-- >0)r.push(0);return r.concat(x)}function multiplyKaratsuba(x,y){var n=Math.max(x.length,y.length);if(n<=30)return multiplyLong(x,y);n=Math.ceil(n/2);var b=x.slice(n),a=x.slice(0,n),d=y.slice(n),c=y.slice(0,n);var ac=multiplyKaratsuba(a,c),bd=multiplyKaratsuba(b,d),abcd=multiplyKaratsuba(addAny(a,b),addAny(c,d));var product=addAny(addAny(ac,shiftLeft(subtract(subtract(abcd,ac),bd),n)),shiftLeft(bd,2*n));trim(product);return product}function useKaratsuba(l1,l2){return-.012*l1-.012*l2+15e-6*l1*l2>0}BigInteger.prototype.multiply=function(v){var n=parseValue(v),a=this.value,b=n.value,sign=this.sign!==n.sign,abs;if(n.isSmall){if(b===0)return Integer[0];if(b===1)return this;if(b===-1)return this.negate();abs=Math.abs(b);if(abs<BASE){return new BigInteger(multiplySmall(a,abs),sign)}b=smallToArray(abs)}if(useKaratsuba(a.length,b.length))return new BigInteger(multiplyKaratsuba(a,b),sign);return new BigInteger(multiplyLong(a,b),sign)};BigInteger.prototype.times=BigInteger.prototype.multiply;function multiplySmallAndArray(a,b,sign){if(a<BASE){return new BigInteger(multiplySmall(b,a),sign)}return new BigInteger(multiplyLong(b,smallToArray(a)),sign)}SmallInteger.prototype._multiplyBySmall=function(a){if(isPrecise(a.value*this.value)){return new SmallInteger(a.value*this.value)}return multiplySmallAndArray(Math.abs(a.value),smallToArray(Math.abs(this.value)),this.sign!==a.sign)};BigInteger.prototype._multiplyBySmall=function(a){if(a.value===0)return Integer[0];if(a.value===1)return this;if(a.value===-1)return this.negate();return multiplySmallAndArray(Math.abs(a.value),this.value,this.sign!==a.sign)};SmallInteger.prototype.multiply=function(v){return parseValue(v)._multiplyBySmall(this)};SmallInteger.prototype.times=SmallInteger.prototype.multiply;function square(a){var l=a.length,r=createArray(l+l),base=BASE,product,carry,i,a_i,a_j;for(i=0;i<l;i++){a_i=a[i];for(var j=0;j<l;j++){a_j=a[j];product=a_i*a_j+r[i+j];carry=Math.floor(product/base);r[i+j]=product-carry*base;r[i+j+1]+=carry}}trim(r);return r}BigInteger.prototype.square=function(){return new BigInteger(square(this.value),false)};SmallInteger.prototype.square=function(){var value=this.value*this.value;if(isPrecise(value))return new SmallInteger(value);return new BigInteger(square(smallToArray(Math.abs(this.value))),false)};function divMod1(a,b){var a_l=a.length,b_l=b.length,base=BASE,result=createArray(b.length),divisorMostSignificantDigit=b[b_l-1],lambda=Math.ceil(base/(2*divisorMostSignificantDigit)),remainder=multiplySmall(a,lambda),divisor=multiplySmall(b,lambda),quotientDigit,shift,carry,borrow,i,l,q;if(remainder.length<=a_l)remainder.push(0);divisor.push(0);divisorMostSignificantDigit=divisor[b_l-1];for(shift=a_l-b_l;shift>=0;shift--){quotientDigit=base-1;if(remainder[shift+b_l]!==divisorMostSignificantDigit){quotientDigit=Math.floor((remainder[shift+b_l]*base+remainder[shift+b_l-1])/divisorMostSignificantDigit)}carry=0;borrow=0;l=divisor.length;for(i=0;i<l;i++){carry+=quotientDigit*divisor[i];q=Math.floor(carry/base);borrow+=remainder[shift+i]-(carry-q*base);carry=q;if(borrow<0){remainder[shift+i]=borrow+base;borrow=-1}else{remainder[shift+i]=borrow;borrow=0}}while(borrow!==0){quotientDigit-=1;carry=0;for(i=0;i<l;i++){carry+=remainder[shift+i]-base+divisor[i];if(carry<0){remainder[shift+i]=carry+base;carry=0}else{remainder[shift+i]=carry;carry=1}}borrow+=carry}result[shift]=quotientDigit}remainder=divModSmall(remainder,lambda)[0];return[arrayToSmall(result),arrayToSmall(remainder)]}function divMod2(a,b){var a_l=a.length,b_l=b.length,result=[],part=[],base=BASE,guess,xlen,highx,highy,check;while(a_l){part.unshift(a[--a_l]);trim(part);if(compareAbs(part,b)<0){result.push(0);continue}xlen=part.length;highx=part[xlen-1]*base+part[xlen-2];highy=b[b_l-1]*base+b[b_l-2];if(xlen>b_l){highx=(highx+1)*base}guess=Math.ceil(highx/highy);do{check=multiplySmall(b,guess);if(compareAbs(check,part)<=0)break;guess--}while(guess);result.push(guess);part=subtract(part,check)}result.reverse();return[arrayToSmall(result),arrayToSmall(part)]}function divModSmall(value,lambda){var length=value.length,quotient=createArray(length),base=BASE,i,q,remainder,divisor;remainder=0;for(i=length-1;i>=0;--i){divisor=remainder*base+value[i];q=truncate(divisor/lambda);remainder=divisor-q*lambda;quotient[i]=q|0}return[quotient,remainder|0]}function divModAny(self,v){var value,n=parseValue(v);var a=self.value,b=n.value;var quotient;if(b===0)throw new Error("Cannot divide by zero");if(self.isSmall){if(n.isSmall){return[new SmallInteger(truncate(a/b)),new SmallInteger(a%b)]}return[Integer[0],self]}if(n.isSmall){if(b===1)return[self,Integer[0]];if(b==-1)return[self.negate(),Integer[0]];var abs=Math.abs(b);if(abs<BASE){value=divModSmall(a,abs);quotient=arrayToSmall(value[0]);var remainder=value[1];if(self.sign)remainder=-remainder;if(typeof quotient==="number"){if(self.sign!==n.sign)quotient=-quotient;return[new SmallInteger(quotient),new SmallInteger(remainder)]}return[new BigInteger(quotient,self.sign!==n.sign),new SmallInteger(remainder)]}b=smallToArray(abs)}var comparison=compareAbs(a,b);if(comparison===-1)return[Integer[0],self];if(comparison===0)return[Integer[self.sign===n.sign?1:-1],Integer[0]];if(a.length+b.length<=200)value=divMod1(a,b);else value=divMod2(a,b);quotient=value[0];var qSign=self.sign!==n.sign,mod=value[1],mSign=self.sign;if(typeof quotient==="number"){if(qSign)quotient=-quotient;quotient=new SmallInteger(quotient)}else quotient=new BigInteger(quotient,qSign);if(typeof mod==="number"){if(mSign)mod=-mod;mod=new SmallInteger(mod)}else mod=new BigInteger(mod,mSign);return[quotient,mod]}BigInteger.prototype.divmod=function(v){var result=divModAny(this,v);return{quotient:result[0],remainder:result[1]}};SmallInteger.prototype.divmod=BigInteger.prototype.divmod;BigInteger.prototype.divide=function(v){return divModAny(this,v)[0]};SmallInteger.prototype.over=SmallInteger.prototype.divide=BigInteger.prototype.over=BigInteger.prototype.divide;BigInteger.prototype.mod=function(v){return divModAny(this,v)[1]};SmallInteger.prototype.remainder=SmallInteger.prototype.mod=BigInteger.prototype.remainder=BigInteger.prototype.mod;BigInteger.prototype.pow=function(v){var n=parseValue(v),a=this.value,b=n.value,value,x,y;if(b===0)return Integer[1];if(a===0)return Integer[0];if(a===1)return Integer[1];if(a===-1)return n.isEven()?Integer[1]:Integer[-1];if(n.sign){return Integer[0]}if(!n.isSmall)throw new Error("The exponent "+n.toString()+" is too large.");if(this.isSmall){if(isPrecise(value=Math.pow(a,b)))return new SmallInteger(truncate(value))}x=this;y=Integer[1];while(true){if(b&1===1){y=y.times(x);--b}if(b===0)break;b/=2;x=x.square()}return y};SmallInteger.prototype.pow=BigInteger.prototype.pow;BigInteger.prototype.modPow=function(exp,mod){exp=parseValue(exp);mod=parseValue(mod);if(mod.isZero())throw new Error("Cannot take modPow with modulus 0");var r=Integer[1],base=this.mod(mod);while(exp.isPositive()){if(base.isZero())return Integer[0];if(exp.isOdd())r=r.multiply(base).mod(mod);exp=exp.divide(2);base=base.square().mod(mod)}return r};SmallInteger.prototype.modPow=BigInteger.prototype.modPow;function compareAbs(a,b){if(a.length!==b.length){return a.length>b.length?1:-1}for(var i=a.length-1;i>=0;i--){if(a[i]!==b[i])return a[i]>b[i]?1:-1}return 0}BigInteger.prototype.compareAbs=function(v){var n=parseValue(v),a=this.value,b=n.value;if(n.isSmall)return 1;return compareAbs(a,b)};SmallInteger.prototype.compareAbs=function(v){var n=parseValue(v),a=Math.abs(this.value),b=n.value;if(n.isSmall){b=Math.abs(b);return a===b?0:a>b?1:-1}return-1};BigInteger.prototype.compare=function(v){if(v===Infinity){return-1}if(v===-Infinity){return 1}var n=parseValue(v),a=this.value,b=n.value;if(this.sign!==n.sign){return n.sign?1:-1}if(n.isSmall){return this.sign?-1:1}return compareAbs(a,b)*(this.sign?-1:1)};BigInteger.prototype.compareTo=BigInteger.prototype.compare;SmallInteger.prototype.compare=function(v){if(v===Infinity){return-1}if(v===-Infinity){return 1}var n=parseValue(v),a=this.value,b=n.value;if(n.isSmall){return a==b?0:a>b?1:-1}if(a<0!==n.sign){return a<0?-1:1}return a<0?1:-1};SmallInteger.prototype.compareTo=SmallInteger.prototype.compare;BigInteger.prototype.equals=function(v){return this.compare(v)===0};SmallInteger.prototype.eq=SmallInteger.prototype.equals=BigInteger.prototype.eq=BigInteger.prototype.equals;BigInteger.prototype.notEquals=function(v){return this.compare(v)!==0};SmallInteger.prototype.neq=SmallInteger.prototype.notEquals=BigInteger.prototype.neq=BigInteger.prototype.notEquals;BigInteger.prototype.greater=function(v){return this.compare(v)>0};SmallInteger.prototype.gt=SmallInteger.prototype.greater=BigInteger.prototype.gt=BigInteger.prototype.greater;BigInteger.prototype.lesser=function(v){return this.compare(v)<0};SmallInteger.prototype.lt=SmallInteger.prototype.lesser=BigInteger.prototype.lt=BigInteger.prototype.lesser;BigInteger.prototype.greaterOrEquals=function(v){return this.compare(v)>=0};SmallInteger.prototype.geq=SmallInteger.prototype.greaterOrEquals=BigInteger.prototype.geq=BigInteger.prototype.greaterOrEquals;BigInteger.prototype.lesserOrEquals=function(v){return this.compare(v)<=0};SmallInteger.prototype.leq=SmallInteger.prototype.lesserOrEquals=BigInteger.prototype.leq=BigInteger.prototype.lesserOrEquals;BigInteger.prototype.isEven=function(){return(this.value[0]&1)===0};SmallInteger.prototype.isEven=function(){return(this.value&1)===0};BigInteger.prototype.isOdd=function(){return(this.value[0]&1)===1};SmallInteger.prototype.isOdd=function(){return(this.value&1)===1};BigInteger.prototype.isPositive=function(){return!this.sign};SmallInteger.prototype.isPositive=function(){return this.value>0};BigInteger.prototype.isNegative=function(){return this.sign};SmallInteger.prototype.isNegative=function(){return this.value<0};BigInteger.prototype.isUnit=function(){return false};SmallInteger.prototype.isUnit=function(){return Math.abs(this.value)===1};BigInteger.prototype.isZero=function(){return false};SmallInteger.prototype.isZero=function(){return this.value===0};BigInteger.prototype.isDivisibleBy=function(v){var n=parseValue(v);var value=n.value;if(value===0)return false;if(value===1)return true;if(value===2)return this.isEven();return this.mod(n).equals(Integer[0])};SmallInteger.prototype.isDivisibleBy=BigInteger.prototype.isDivisibleBy;function isBasicPrime(v){var n=v.abs();if(n.isUnit())return false;if(n.equals(2)||n.equals(3)||n.equals(5))return true;if(n.isEven()||n.isDivisibleBy(3)||n.isDivisibleBy(5))return false;if(n.lesser(25))return true}BigInteger.prototype.isPrime=function(){var isPrime=isBasicPrime(this);if(isPrime!==undefined)return isPrime;var n=this.abs(),nPrev=n.prev();var a=[2,3,5,7,11,13,17,19],b=nPrev,d,t,i,x;while(b.isEven())b=b.divide(2);for(i=0;i<a.length;i++){x=bigInt(a[i]).modPow(b,n);if(x.equals(Integer[1])||x.equals(nPrev))continue;for(t=true,d=b;t&&d.lesser(nPrev);d=d.multiply(2)){x=x.square().mod(n);if(x.equals(nPrev))t=false}if(t)return false}return true};SmallInteger.prototype.isPrime=BigInteger.prototype.isPrime;BigInteger.prototype.isProbablePrime=function(iterations){var isPrime=isBasicPrime(this);if(isPrime!==undefined)return isPrime;var n=this.abs();var t=iterations===undefined?5:iterations;for(var i=0;i<t;i++){var a=bigInt.randBetween(2,n.minus(2));if(!a.modPow(n.prev(),n).isUnit())return false}return true};SmallInteger.prototype.isProbablePrime=BigInteger.prototype.isProbablePrime;BigInteger.prototype.modInv=function(n){var t=bigInt.zero,newT=bigInt.one,r=parseValue(n),newR=this.abs(),q,lastT,lastR;while(!newR.equals(bigInt.zero)){q=r.divide(newR);lastT=t;lastR=r;t=newT;r=newR;newT=lastT.subtract(q.multiply(newT));newR=lastR.subtract(q.multiply(newR))}if(!r.equals(1))throw new Error(this.toString()+" and "+n.toString()+" are not co-prime");if(t.compare(0)===-1){t=t.add(n)}if(this.isNegative()){return t.negate()}return t};SmallInteger.prototype.modInv=BigInteger.prototype.modInv;BigInteger.prototype.next=function(){var value=this.value;if(this.sign){return subtractSmall(value,1,this.sign)}return new BigInteger(addSmall(value,1),this.sign)};SmallInteger.prototype.next=function(){var value=this.value;if(value+1<MAX_INT)return new SmallInteger(value+1);return new BigInteger(MAX_INT_ARR,false)};BigInteger.prototype.prev=function(){var value=this.value;if(this.sign){return new BigInteger(addSmall(value,1),true)}return subtractSmall(value,1,this.sign)};SmallInteger.prototype.prev=function(){var value=this.value;if(value-1>-MAX_INT)return new SmallInteger(value-1);return new BigInteger(MAX_INT_ARR,true)};var powersOfTwo=[1];while(2*powersOfTwo[powersOfTwo.length-1]<=BASE)powersOfTwo.push(2*powersOfTwo[powersOfTwo.length-1]);var powers2Length=powersOfTwo.length,highestPower2=powersOfTwo[powers2Length-1];function shift_isSmall(n){return(typeof n==="number"||typeof n==="string")&&+Math.abs(n)<=BASE||n instanceof BigInteger&&n.value.length<=1}BigInteger.prototype.shiftLeft=function(n){if(!shift_isSmall(n)){throw new Error(String(n)+" is too large for shifting.")}n=+n;if(n<0)return this.shiftRight(-n);var result=this;while(n>=powers2Length){result=result.multiply(highestPower2);n-=powers2Length-1}return result.multiply(powersOfTwo[n])};SmallInteger.prototype.shiftLeft=BigInteger.prototype.shiftLeft;BigInteger.prototype.shiftRight=function(n){var remQuo;if(!shift_isSmall(n)){throw new Error(String(n)+" is too large for shifting.")}n=+n;if(n<0)return this.shiftLeft(-n);var result=this;while(n>=powers2Length){if(result.isZero())return result;remQuo=divModAny(result,highestPower2);result=remQuo[1].isNegative()?remQuo[0].prev():remQuo[0];n-=powers2Length-1}remQuo=divModAny(result,powersOfTwo[n]);return remQuo[1].isNegative()?remQuo[0].prev():remQuo[0]};SmallInteger.prototype.shiftRight=BigInteger.prototype.shiftRight;function bitwise(x,y,fn){y=parseValue(y);var xSign=x.isNegative(),ySign=y.isNegative();var xRem=xSign?x.not():x,yRem=ySign?y.not():y;var xDigit=0,yDigit=0;var xDivMod=null,yDivMod=null;var result=[];while(!xRem.isZero()||!yRem.isZero()){xDivMod=divModAny(xRem,highestPower2);xDigit=xDivMod[1].toJSNumber();if(xSign){xDigit=highestPower2-1-xDigit}yDivMod=divModAny(yRem,highestPower2);yDigit=yDivMod[1].toJSNumber();if(ySign){yDigit=highestPower2-1-yDigit}xRem=xDivMod[0];yRem=yDivMod[0];result.push(fn(xDigit,yDigit))}var sum=fn(xSign?1:0,ySign?1:0)!==0?bigInt(-1):bigInt(0);for(var i=result.length-1;i>=0;i-=1){sum=sum.multiply(highestPower2).add(bigInt(result[i]))}return sum}BigInteger.prototype.not=function(){return this.negate().prev()};SmallInteger.prototype.not=BigInteger.prototype.not;BigInteger.prototype.and=function(n){return bitwise(this,n,function(a,b){return a&b})};SmallInteger.prototype.and=BigInteger.prototype.and;BigInteger.prototype.or=function(n){return bitwise(this,n,function(a,b){return a|b})};SmallInteger.prototype.or=BigInteger.prototype.or;BigInteger.prototype.xor=function(n){return bitwise(this,n,function(a,b){return a^b})};SmallInteger.prototype.xor=BigInteger.prototype.xor;var LOBMASK_I=1<<30,LOBMASK_BI=(BASE&-BASE)*(BASE&-BASE)|LOBMASK_I;function roughLOB(n){var v=n.value,x=typeof v==="number"?v|LOBMASK_I:v[0]+v[1]*BASE|LOBMASK_BI;return x&-x}function integerLogarithm(value,base){if(base.compareTo(value)<=0){var tmp=integerLogarithm(value,base.square(base));var p=tmp.p;var e=tmp.e;var t=p.multiply(base);return t.compareTo(value)<=0?{p:t,e:e*2+1}:{p:p,e:e*2}}return{p:bigInt(1),e:0}}BigInteger.prototype.bitLength=function(){var n=this;if(n.compareTo(bigInt(0))<0){n=n.negate().subtract(bigInt(1))}if(n.compareTo(bigInt(0))===0){return bigInt(0)}return bigInt(integerLogarithm(n,bigInt(2)).e).add(bigInt(1))};SmallInteger.prototype.bitLength=BigInteger.prototype.bitLength;function max(a,b){a=parseValue(a);b=parseValue(b);return a.greater(b)?a:b}function min(a,b){a=parseValue(a);b=parseValue(b);return a.lesser(b)?a:b}function gcd(a,b){a=parseValue(a).abs();b=parseValue(b).abs();if(a.equals(b))return a;if(a.isZero())return b;if(b.isZero())return a;var c=Integer[1],d,t;while(a.isEven()&&b.isEven()){d=Math.min(roughLOB(a),roughLOB(b));a=a.divide(d);b=b.divide(d);c=c.multiply(d)}while(a.isEven()){a=a.divide(roughLOB(a))}do{while(b.isEven()){b=b.divide(roughLOB(b))}if(a.greater(b)){t=b;b=a;a=t}b=b.subtract(a)}while(!b.isZero());return c.isUnit()?a:a.multiply(c)}function lcm(a,b){a=parseValue(a).abs();b=parseValue(b).abs();return a.divide(gcd(a,b)).multiply(b)}function randBetween(a,b){a=parseValue(a);b=parseValue(b);var low=min(a,b),high=max(a,b);var range=high.subtract(low).add(1);if(range.isSmall)return low.add(Math.floor(Math.random()*range));var length=range.value.length-1;var result=[],restricted=true;for(var i=length;i>=0;i--){var top=restricted?range.value[i]:BASE;var digit=truncate(Math.random()*top);result.unshift(digit);if(digit<top)restricted=false}result=arrayToSmall(result);return low.add(typeof result==="number"?new SmallInteger(result):new BigInteger(result,false))}var parseBase=function(text,base){var length=text.length;var i;var absBase=Math.abs(base);for(var i=0;i<length;i++){var c=text[i].toLowerCase();if(c==="-")continue;if(/[a-z0-9]/.test(c)){if(/[0-9]/.test(c)&&+c>=absBase){if(c==="1"&&absBase===1)continue;throw new Error(c+" is not a valid digit in base "+base+".")}else if(c.charCodeAt(0)-87>=absBase){throw new Error(c+" is not a valid digit in base "+base+".")}}}if(2<=base&&base<=36){if(length<=LOG_MAX_INT/Math.log(base)){var result=parseInt(text,base);if(isNaN(result)){throw new Error(c+" is not a valid digit in base "+base+".")}return new SmallInteger(parseInt(text,base))}}base=parseValue(base);var digits=[];var isNegative=text[0]==="-";for(i=isNegative?1:0;i<text.length;i++){var c=text[i].toLowerCase(),charCode=c.charCodeAt(0);if(48<=charCode&&charCode<=57)digits.push(parseValue(c));else if(97<=charCode&&charCode<=122)digits.push(parseValue(c.charCodeAt(0)-87));else if(c==="<"){var start=i;do{i++}while(text[i]!==">");digits.push(parseValue(text.slice(start+1,i)))}else throw new Error(c+" is not a valid character")}return parseBaseFromArray(digits,base,isNegative)};function parseBaseFromArray(digits,base,isNegative){var val=Integer[0],pow=Integer[1],i;for(i=digits.length-1;i>=0;i--){val=val.add(digits[i].times(pow));pow=pow.times(base)}return isNegative?val.negate():val}function stringify(digit){if(digit<=35){return"0123456789abcdefghijklmnopqrstuvwxyz".charAt(digit)}return"<"+digit+">"}function toBase(n,base){base=bigInt(base);if(base.isZero()){if(n.isZero())return{value:[0],isNegative:false};throw new Error("Cannot convert nonzero numbers to base 0.")}if(base.equals(-1)){if(n.isZero())return{value:[0],isNegative:false};if(n.isNegative())return{value:[].concat.apply([],Array.apply(null,Array(-n)).map(Array.prototype.valueOf,[1,0])),isNegative:false};var arr=Array.apply(null,Array(+n-1)).map(Array.prototype.valueOf,[0,1]);arr.unshift([1]);return{value:[].concat.apply([],arr),isNegative:false}}var neg=false;if(n.isNegative()&&base.isPositive()){neg=true;n=n.abs()}if(base.equals(1)){if(n.isZero())return{value:[0],isNegative:false};return{value:Array.apply(null,Array(+n)).map(Number.prototype.valueOf,1),isNegative:neg}}var out=[];var left=n,divmod;while(left.isNegative()||left.compareAbs(base)>=0){divmod=left.divmod(base);left=divmod.quotient;var digit=divmod.remainder;if(digit.isNegative()){digit=base.minus(digit).abs();left=left.next()}out.push(digit.toJSNumber())}out.push(left.toJSNumber());return{value:out.reverse(),isNegative:neg}}function toBaseString(n,base){var arr=toBase(n,base);return(arr.isNegative?"-":"")+arr.value.map(stringify).join("")}BigInteger.prototype.toArray=function(radix){return toBase(this,radix)};SmallInteger.prototype.toArray=function(radix){return toBase(this,radix)};BigInteger.prototype.toString=function(radix){if(radix===undefined)radix=10;if(radix!==10)return toBaseString(this,radix);var v=this.value,l=v.length,str=String(v[--l]),zeros="0000000",digit;while(--l>=0){digit=String(v[l]);str+=zeros.slice(digit.length)+digit}var sign=this.sign?"-":"";return sign+str};SmallInteger.prototype.toString=function(radix){if(radix===undefined)radix=10;if(radix!=10)return toBaseString(this,radix);return String(this.value)};BigInteger.prototype.toJSON=SmallInteger.prototype.toJSON=function(){return this.toString()};BigInteger.prototype.valueOf=function(){return parseInt(this.toString(),10)};BigInteger.prototype.toJSNumber=BigInteger.prototype.valueOf;SmallInteger.prototype.valueOf=function(){return this.value};SmallInteger.prototype.toJSNumber=SmallInteger.prototype.valueOf;function parseStringValue(v){if(isPrecise(+v)){var x=+v;if(x===truncate(x))return new SmallInteger(x);throw new Error("Invalid integer: "+v)}var sign=v[0]==="-";if(sign)v=v.slice(1);var split=v.split(/e/i);if(split.length>2)throw new Error("Invalid integer: "+split.join("e"));if(split.length===2){var exp=split[1];if(exp[0]==="+")exp=exp.slice(1);exp=+exp;if(exp!==truncate(exp)||!isPrecise(exp))throw new Error("Invalid integer: "+exp+" is not a valid exponent.");var text=split[0];var decimalPlace=text.indexOf(".");if(decimalPlace>=0){exp-=text.length-decimalPlace-1;text=text.slice(0,decimalPlace)+text.slice(decimalPlace+1)}if(exp<0)throw new Error("Cannot include negative exponent part for integers");text+=new Array(exp+1).join("0");v=text}var isValid=/^([0-9][0-9]*)$/.test(v);if(!isValid)throw new Error("Invalid integer: "+v);var r=[],max=v.length,l=LOG_BASE,min=max-l;while(max>0){r.push(+v.slice(min,max));min-=l;if(min<0)min=0;max-=l}trim(r);return new BigInteger(r,sign)}function parseNumberValue(v){if(isPrecise(v)){if(v!==truncate(v))throw new Error(v+" is not an integer.");return new SmallInteger(v)}return parseStringValue(v.toString())}function parseValue(v){if(typeof v==="number"){return parseNumberValue(v)}if(typeof v==="string"){return parseStringValue(v)}return v}for(var i=0;i<1e3;i++){Integer[i]=new SmallInteger(i);if(i>0)Integer[-i]=new SmallInteger(-i)}Integer.one=Integer[1];Integer.zero=Integer[0];Integer.minusOne=Integer[-1];Integer.max=max;Integer.min=min;Integer.gcd=gcd;Integer.lcm=lcm;Integer.isInstance=function(x){return x instanceof BigInteger||x instanceof SmallInteger};Integer.randBetween=randBetween;Integer.fromArray=function(digits,base,isNegative){return parseBaseFromArray(digits.map(parseValue),parseValue(base||10),isNegative)};return Integer}();if(typeof module!=="undefined"&&module.hasOwnProperty("exports")){module.exports=bigInt}if(typeof define==="function"&&define.amd){define("big-integer",[],function(){return bigInt})}
/** ItemsGrid\itemsGridCommands.js **/
function onInitialize() {
	return ItemTypeGrid.onInitialize();
}

function onReinitialize(itemTN, itemTID, _savedSearchId) {
	previewPane.clearForm();

	if (itemTypeID == itemTID && savedSearchId == _savedSearchId) {
		return;
	}

	if (columnSelectionMediator) {
		columnSelectionMediator.closeColumnSelectionWindow();
		columnSelectionMediator.closeXClassBarWindow();
	}

	stopSearch(false);
	saveSetups(true);

	itemTypeID = itemTID;
	savedSearchId = _savedSearchId;
	ItemTypeGrid = MainGridFactory.Create(itemTN);

	if (onInitialize()) {
		InitPropertiesContainer();
		initSearch();
		reinitXClassBar();
	}
}

function initSearch() {
	searchReady = false;
	initToolbar();
	initPaginationToolbar();
	setupPageNumber();
	setupGrid(true);

	if (searchContainer) {
		searchContainer.removeIFramesCollection();
	}
	const searchToolbar = document.querySelector('#searchview-toolbars .aras-commandbar');
	searchContainer = new SearchContainer(
		itemTypeName,
		null,
		grid,
		null,
		searchLocation,
		document.getElementById('searchPlaceholder'),
		undefined,
		pagination,
		searchToolbar
	);
	searchContainer.initSearchContainer(true);
	searchContainer.onStartSearchContainer();
	updateToolStatusBar();

	if (savedSearchId) {
		searchContainer._onSavedSearchChange(savedSearchId);
	}
	searchReady = true;
	// run autosearch if required
	if (aras.getItemProperty(currItemType, 'auto_search') == '1' || Boolean(savedSearchId) || Boolean(autoSearch)) {
		var statusId = aras.showStatusMessage('status', aras.getResource('', 'itemsgrid.populating_grid_with_it_items', itemTypeLabel));
		var searchResult = doSearch();

		aras.clearStatusMessage(statusId);
		return searchResult;
	}
}

function initColumnSelectionBlock() {
	const xClassBarNode = document.getElementById('xClassBarPlaceholder');
	columnSelectionMediator = ColumnSelectionMediatorFactory.CreateBaseMediator(xClassBarNode);
	columnSelectionControl.initResources();
	xClassSearchWrapper.initResources();
}

function reinitXClassBar() {
	const xClassBarNode = document.getElementById('xClassBarPlaceholder');
	columnSelectionMediator.xClassBarWrapper = new XClassBar(itemTypeName, xClassBarNode);
}

function startCellEditIG(rowId, field, cleanIfNeed) {
	startCellEditCommon.call(this, rowId, field);
}

function applyCellEditIG(rowId, field, cleanIfNeed) {
	if ('input_row' == rowId && searchReady) {
		removeFilterListValueIfNeed(rowId, field);
	}

	applyCellEditCommon.call(this, rowId, field);
}

function showReleaseEffectiveDateRows(isShow) {
	if (!document.getElementById('release_date_row') || !document.getElementById('effective_date_row')) {
		return;
	}

	document.getElementById('release_date_row').style.display = isShow ? '' : 'none';
	document.getElementById('effective_date_row').style.display = isShow ? '' : 'none';
}

function generateXML4Item(itemNode) {
	var itemType = itemNode.getAttribute('type');
	var tmpDom = createEmptyResultDom();
	var gridXml;
	var tableNode;
	var nodes;
	var currentNode;
	var i;

	currentNode = tmpDom.selectSingleNode(aras.XPathResult());
	currentNode.appendChild(itemNode.cloneNode(true));

	aras.uiPrepareDOM4XSLT(tmpDom, itemTypeID);
	gridXml = aras.uiGenerateItemsGridXML(tmpDom, visiblePropNds, itemTypeID);
	tmpDom.loadXML(gridXml);

	tableNode = tmpDom.documentElement;
	nodes = tmpDom.selectNodes('/table/*[local-name(.)!=\'tr\']');

	for (i = 0; i < nodes.length; i++) {
		currentNode = nodes[i];
		tableNode.removeChild(currentNode);
	}

	if (itemType == 'RelationshipType') {
		var tdNodes = tmpDom.selectNodes('/table/tr/td');

		const correctNames = function(element, param, cell) {
			if (element != null && element.selectSingleNode('keyed_name') != null) {
				cell.firstChild.data = element.selectSingleNode('keyed_name').text;
			} else if (itemNode.selectSingleNode(param) != null && itemNode.selectSingleNode(param).text != '') {
				var res = aras.getItemById(element, itemNode.selectSingleNode(param).text, 0, '', 'keyed_name');

				if (!res) {
					res = aras.getItemById('ItemType', itemNode.selectSingleNode(param).text, 0, '', 'keyed_name');
				}

				if (res) {
					cell.firstChild.data = res.selectSingleNode('keyed_name').text;
				}
			}
		};

		correctNames(itemNode.selectSingleNode('related_id/Item'), 'related_id', tdNodes[4]);
		correctNames(itemNode.selectSingleNode('source_id/Item'), 'source_id', tdNodes[3]);
	}

	return tmpDom;
}

function updateGridCell(cell, tdNode) {
	if (cell && tdNode) {
		var textColor = tdNode.getAttribute('textColor');
		var itemLink = tdNode.getAttribute('link');
		var bgColor = tdNode.getAttribute('bgColor');
		var font = tdNode.getAttribute('font');

		if (textColor) {
			try {
				cell.setTextColor(textColor);
			} catch (excep) {}
		}

		if (itemLink) {
			cell.setLink(itemLink);
		}

		if (bgColor) {
			try {
				cell.setBgColor_Experimental(bgColor);
			} catch (excep) {}
		}

		if (font) {
			cell.setFont(font);
		}

		cell.setValue(tdNode.text);
	}
}

function updateItemInQueryCache(itemNode) {
	var queryItem = currQryItem.getResult();
	var oldItem = queryItem.selectSingleNode('Item[@id="' + itemNode.getAttribute('id') + '"]');

	if (oldItem) {
		queryItem.replaceChild(itemNode.cloneNode(true), oldItem);
	} else {
		queryItem.appendChild(itemNode.cloneNode(true));
	}
}

function insertRow(itemNode, skipMenuUpdate) {
	if (itemNode && itemNode.getAttribute('type') == itemTypeName) {
		var generatedDom;

		updateItemInQueryCache(itemNode);
		generatedDom = generateXML4Item(itemNode);

		xml_ready_flag = false;
		addRowInProgress_Number++;
		grid.addXMLRows(generatedDom.xml);

		if (!skipMenuUpdate) {
			updateToolStatusBar();
		}

		return true;
	}

	return false;
}

function checkBeforeUpdateRow() {
	var columnWidths = aras.getPreferenceItemProperty('Core_ItemGridLayout', itemTypeID, 'col_widths', null);

	if (!columnWidths) {
		onInitialize();
		initSearch();

		return false;
	}

	return true;
}

function updateRow(itemNode, skipMenuUpdate) {
	if (itemNode && checkBeforeUpdateRow()) {
		var itemId = itemNode.getAttribute('id');

		if (grid.getRowIndex(itemId) == -1) {
			return insertRow(itemNode, skipMenuUpdate);
		} else {
			var tmpDom = generateXML4Item(itemNode);
			var tdNodes = tmpDom.selectNodes('/table/tr/td');
			var tdNode;
			var gridCell;
			var i;

			updateItemInQueryCache(itemNode);

			for (i = 0; i < tdNodes.length; i++) {
				tdNode = tdNodes[i];

				gridCell = grid.cells(itemId, i);
				updateGridCell(gridCell, tdNode);
			}

			if (itemId == grid.getSelectedId()) {
				onSelectItem(itemId, undefined, skipMenuUpdate);
			}

			previewPane.updateForm(itemId, itemTypeName);
			return true;
		}
	}

	return false;
}

function deleteRow(deleteTarget, skipQuery) {
	if (deleteTarget) {
		var itemId;

		if (typeof (deleteTarget) == 'string') {
			itemId = deleteTarget;
		} else {
			if (deleteTarget.getAttribute('type') == itemTypeName) {
				itemId = deleteTarget.getAttribute('id');
			} else {
				return false;
			}
		}

		if (itemId == grid.getSelectedId()) {
			aras.uiPopulateInfoTableWithItem(null, document);
		}

		grid.deleteRow(itemId);
		previewPane.clearForm(itemId);
		if (!skipQuery) {
			var itemNode = currQryItem.getResult().selectSingleNode('Item[@id="' + itemId + '"]');

			if (itemNode) {
				// If we delete versionable item, all previous versions should be removed to.
				// IR-008031 "The previous version is shown after manual version".
				var config_id = aras.getItemProperty(itemNode, 'config_id');

				if (isVersionableIT && config_id) {
					var nodesToDelete = currQryItem.getResult().selectNodes('Item[@type="' + itemTypeName + '"][config_id="' + config_id + '"]');
					var i;

					for (i = 0; i < nodesToDelete.length; i++) {
						nodesToDelete[i].parentNode.removeChild(nodesToDelete[i]);
					}
				} else {
					itemNode.parentNode.removeChild(itemNode);
				}
			}
		}

		updateToolStatusBar();
	} else {
		aras.uiPopulateInfoTableWithItem(null, document);
		return false;
	}
}

function updateRowSearchGrids(itemNode) {
	return syncGrids('updateRow', itemNode);
}

function deleteRowSearchGrids(deleteTarget) {
	if (!deleteTarget) {
		aras.uiPopulateInfoTableWithItem(null, document);
		return false;
	}
	return syncGrids('deleteRow', deleteTarget);
}

function insertRowSearchGrids(itemNode) {
	return syncGrids('insertRow', itemNode);
}

function syncGrids(syncFunction, itemNode) {
	if (!itemNode) {
		return false;
	}
	const topWin = aras.getMainWindow();
	const itemsGridArray = topWin.arasTabs.getSearchGridTabs(window.itemTypeID);
	const changedGrids = itemsGridArray.filter(function(itemsGrid) {
		return itemsGrid[syncFunction](itemNode);
	});

	return changedGrids.length > 0;
}

function emptyGrid() {
	deleteRow(grid.getSelectedId(), true);
	grid.RemoveAllRows();
}

function setFrozenColumns() {
	if (this._grid.view.defaultSettings.freezableColumns) {
		var frozenColumns = aras.getPreferenceItemProperty('Core_ItemGridLayout', itemTypeID, 'frozen_columns', '1');
		grid._grid.settings.frozenColumns = parseInt(frozenColumns, 10);
	}
}

function onXmlLoaded() {
	if (addRowInProgress_Number == 0) {
		// jscs:disable
		with (aras) { // jshint ignore:line
			// jscs:enable
			if (!sGridsSetups[itemTypeName].selectedRows) {
				sGridsSetups[itemTypeName].selectedRows = [];
			}

			var selectedRows = sGridsSetups[itemTypeName].selectedRows;
			var rowToSelId = '';
			if (grid.getRowCount() > 0) {
				var currSelRows = [];

				if (selectedRows.length == 0) {
					rowToSelId = grid.getRowId(0);
					currSelRows[0] = rowToSelId;
				} else {
					var highestRow = 1000000;
					var rowId;
					var rowIndex;
					var i;

					for (i = 0; i < selectedRows.length; i++) {
						rowId = selectedRows[i];
						rowIndex = grid.getRowIndex(rowId);

						if (rowIndex > -1) {
							if (rowToSelId == '' || rowIndex < highestRow) {
								highestRow = rowIndex;
								rowToSelId = rowId;
							}

							currSelRows[currSelRows.length] = rowId;
							grid.setSelectedRow(rowId, true, false);
						}
					}

					if (currSelRows.length == 0) {
						rowToSelId = grid.getRowId(0);
						currSelRows[0] = rowToSelId;
						grid.setSelectedRow(rowToSelId, true, false);
					}
				}
				grid.setSelectedRow(rowToSelId, true, true);
				sGridsSetups[itemTypeName].selectedRows = currSelRows;

				onSelectItem(rowToSelId);
			} else {
				updateInfoTableWithItem(rowToSelId);
			}
		}
	} else {
		addRowInProgress_Number--;
		if (addRowInProgress_Number == 0) {
			if (callbackF_afterAddRow) {
				callbackF_afterAddRow();
			}
		}
	}

	xml_ready_flag = true;
}

function updateInfoTableWithItem(rowId) {
	var currentQueryItemResult = currQryItem.getResult();
	var sourceItem = currentQueryItemResult.selectSingleNode('Item[@id="' + rowId + '"]');

	aras.uiPopulateInfoTableWithItem(sourceItem, document, function(soapBody, callback) {
		asyncController.sendRequest(rowId, 'updateInfoTableWithItem', soapBody, callback);
	}, function(soapBody, callback) {
		asyncController.sendRequest(rowId, 'requestLCStateHanlder', soapBody, callback);
	});

	if (columnSelectionMediator) {
		columnSelectionMediator.updateXClassBar();
	}
}

function onSelectItem(rowId, col, notupdateMenu, isGridEvent) {
	var idsArray = grid.getSelectedItemIds();
	var rowIsNotSelected = (idsArray.indexOf(rowId) === -1);

	aras.sGridsSetups[itemTypeName].selectedRows = idsArray;
	if (idsArray.indexOf(rowId) >= 0) {
		updateInfoTableWithItem(rowId);
		onClickRow(rowId);
	} else {
		updateInfoTableWithItem(idsArray[0]);
		onClickRow(idsArray[0] || rowId);
	}

	if (rowIsNotSelected && !isGridEvent) {
		grid.setSelectedRow(rowId, true, false);
	}

	if (!notupdateMenu) {
		setMenuState(rowId, col);
	}

	columnSelectionMediator.updateXClassBar();
}

function setMenuState(rowId, col) {
	ItemTypeGrid.setMenuState(rowId, col);
}

function initItemMenu(rowId) {
	ItemTypeGrid.initItemMenu(rowId);
}

function onDoubleClick(rowId, columnIndex, altMode) {
	ItemTypeGrid.onDoubleClick(rowId, altMode);
}

function onClickRow(rowId) {
	if (previewPane.getType() !== 'Form') {
		return;
	}

	if (ItemTypeGrid.onClick && rowId) {
		ItemTypeGrid.onClick(rowId);
	} else {
		previewPane.clearForm();
	}
}

function fillPopupMenu(rowId, col) {
	ItemTypeGrid.fillPopupMenu(rowId, col);
}

function onHeaderCellContextMenu(e) {
	return topWnd.cui.onGridHeaderContextMenu(e, grid, true);
}

function onHeaderContextMenu(e) {
	return topWnd.cui.onGridHeaderContextMenu(e, grid);
}

function hideColumn(col) {
	grid.SetColumnVisible(col, false);
}

function showColumn(col) {
	var colOrderArr = grid.getLogicalColumnOrder().split(';');
	var propsToShow = [];
	var propertyName;
	var propertyLabel;
	var propertyWidth;
	var columnName;
	var i;
	var j;

	for (i = 0; i < colOrderArr.length; i++) {
		if (grid.getColWidth(i) == 0) {
			propertyLabel = '';
			propertyWidth = 100;
			columnName = grid.GetColumnName(i);

			if (columnName === 'L') {
				propertyLabel = aras.getResource('', 'common.claimed');
				propertyWidth = 32;
			} else {
				propertyName = columnName.substr(0, columnName.length - 2);

				for (j = 0; j < visiblePropNds.length; j++) {
					if (aras.getItemProperty(visiblePropNds[j], 'name') == propertyName) {
						var tempWidth = parseInt(aras.getItemProperty(visiblePropNds[j], 'column_width'));

						propertyLabel = aras.getItemProperty(visiblePropNds[j], 'label') || propertyName;

						if (!isNaN(tempWidth)) {
							propertyWidth = tempWidth;
						}
						break;
					}
				}
			}
			propsToShow.push({colNumber: i, label: propertyLabel, width: propertyWidth});
		}
	}

	if (propsToShow.length) {
		window.parent.ArasModules.Dialog.show('iframe', {
			title: aras.getResource('', 'showcolumndlg.title'),
			aras: aras,
			propsToShow: propsToShow,
			dialogWidth: 350,
			dialogHeight: 500,
			resizable: true,
			content: 'SitePreference/showColumnDialog.html'
		}).promise.then(function(resultArray) {
			if (resultArray) {
				for (var j = 0; j < resultArray.length; j++) {
					for (var i = 0; i < propsToShow.length; i++) {
						if (propsToShow[i].label === resultArray[j]) {
							grid.SetColumnVisible(propsToShow[i].colNumber, true, propsToShow[i].width);
							break;
						}
					}
				}
			}
		});
	} else {
		aras.AlertError(aras.getResource('', 'itemsgrid.no_additional_columns_available'));
	}
}

function onMenuClicked(commandId, rowId, col) {
	ItemTypeGrid.onMenuClicked(commandId, rowId, col);
}

function onLink(typeName, id, altMode) {
	ItemTypeGrid.onLink(typeName, id, altMode);
}

function GetDatePattern(queryType) {
	var propertyName;
	var datePattern;

	switch (queryType) {
		case 'Released':
			propertyName = 'release_date';
			break;
		case 'Effective':
			propertyName = 'effective_date';
			break;
		default:
			propertyName = 'modified_on';
			break;
	}

	const selector = 'Relationships/Item[@type=\'Property\' and name=\'' + propertyName + '\']';
	const pattern = aras.getItemProperty(
		currItemType.selectSingleNode(selector),
		'pattern'
	);
	datePattern = pattern || 'short_date_time';
	return aras.getDotNetDatePattern(datePattern);
}

function execInTearOffWin(itemId, commandId, param) {
	if (commandId) {
		var itemWindow = aras.uiFindWindowEx(itemId);
		var execResult = null;

		if (itemWindow) {
			if (!aras.isWindowClosed(itemWindow)) {
				if (itemWindow.name != 'work') {
					var tearoff_menu = itemWindow.tearOffMenuController;

					aras.browserHelper.setFocus(itemWindow);

					if (tearoff_menu && tearoff_menu.onClickMenuItem) {
						execResult = tearoff_menu.onClickMenuItem(commandId, param);

						if (!execResult || !execResult.result) {
							execResult = true;
						}
					}
				}
			} else {
				aras.uiUnregWindowEx(itemId);
			}

			if (execResult == null) {
				execResult = true;
			}
		}

		return execResult;
	}

	return false;
}

function onNewCommand() {
	if (itemTypeName === 'File') {
		parent.ArasModules.vault.selectFile().then(function(item) {
			var fileNode = aras.newItem('File', item);
			aras.uiShowItemEx(fileNode, 'new');
			aras.itemsCache.addItem(fileNode);
			insertRowSearchGrids(fileNode);
		});
	} else {
		var itemType = aras.getItemTypeForClient(itemTypeName).node;

		if (aras.isPolymorphic(itemType) && !window.showModalDialog) {
			var itemType=aras.getItemTypeForClient(itemTypeName).node;
			var itemTypesList = aras.getMorphaeList(itemType);
			if(itemTypesList.length==1){
				var new_itemNd = aras.newItem(itemTypesList[0].name);
				aras.itemsCache.addItem(new_itemNd);
				aras.uiShowItemEx(new_itemNd, 'new');
			}
			else{
				aras.newItem(itemTypeName).then(function(node) {
					if (node) {
						aras.itemsCache.addItem(node);
						aras.uiShowItemEx(node, 'new');
						insertRowSearchGrids(node);
					}
				});
			}
		} else {
			var newItem = aras.uiNewItemEx(itemTypeName);

			if (newItem) {
				insertRowSearchGrids(newItem);
			}
		}
	}
}

function onViewCommand() {
	var itemId = grid.getSelectedId();

	if (itemId) {
		if (!execInTearOffWin(itemId, 'view')) {
			var itemNode = aras.getItemById(itemTypeName, itemId, 0);

			if (itemNode) {
				aras.uiShowItemEx(itemNode);
			} else {
				aras.AlertError(aras.getResource('', 'itemsgrid.failed2get_itemtype', itemTypeLabel));
				return false;
			}
		}

		return true;
	} else {
		aras.AlertError(aras.getResource('', 'itemsgrid.select_item_type_first', itemTypeLabel));
		return false;
	}
}

function onEditCommand() {
	var itemId = grid.getSelectedId();

	return ItemTypeGrid.onEditCommand(itemId);
}

function onSaveCommand() {
	var itemNode;
	var itemTypeName = window.itemTypeName;
	var isVersionableIT = window.isVersionableIT;
	var updateGridAfterSave = function(oldItemId, saveResult) {
		if (!saveResult || itemTypeName !== window.itemTypeName) {
			return;
		}
		var newId = oldItemId;
		if (isVersionableIT) {
			itemNode = aras.getItemLastVersion(itemTypeName, oldItemId);

			if (!itemNode) {
				return;
			}
			newId = itemNode.getAttribute('id');
		}

		itemNode = aras.getItemById(itemTypeName, newId, 0);
		if (itemNode) {
			if (isVersionableIT) {
				var oldItem = currQryItem.getResult().selectSingleNode('Item[@id="' + oldItemId + '"]');
				deleteRowSearchGrids(oldItem);
			}

			if (updateRowSearchGrids(itemNode)) {
				onSelectItem(newId);
			}
		}
	};
	var itemIds = grid.getSelectedItemIds();

	if (!itemIds.length) {
		aras.AlertError(aras.getResource('', 'itemsgrid.select_item_type_first', itemTypeLabel));
		return Promise.resolve(false);
	}

	var itemId;
	var i;
	var itemsSavingChain = Promise.resolve();
	for (i = 0; i < itemIds.length; i++) {
		itemId = itemIds[i];

		if (!execInTearOffWin(itemId, 'save')) {
			itemNode = aras.getItemById('', itemId, 0);

			if (itemNode && (aras.isTempEx(itemNode) || aras.isDirtyEx(itemNode))) {
				if (itemTypeName == 'Form') {
					itemNode.setAttribute('levels', 3);
				}
				itemsSavingChain = itemsSavingChain.then(aras.saveItemExAsync.bind(aras, itemNode)).then(updateGridAfterSave.bind(null, itemId));
			}
		}
	}

	itemsSavingChain.then(function() {
		if (itemTypeName !== window.itemTypeName) {
			return;
		}
		switch (itemTypeName) {
			case 'ItemType':
				topWnd.updateTree(itemIds);
				break;
			case 'Preference':
				topWnd.mainLayout.observer.notify('UpdatePreferences');
				break;
		}

		if (itemIds.length === 1) {
			aras.uiReShowItemEx(itemId, itemNode);
		}
	});
}

function onPurgeCommand() {
	return onPurgeDeleteCommand('purge');
}

function onDeleteCommand() {
	return onPurgeDeleteCommand('delete');
}

function onPurgeDeleteCommand(commandId) {
	var itemIds = grid.getSelectedItemIds();

	if (itemIds.length === 0) {
		aras.AlertError(aras.getResource('', 'itemsgrid.select_item_type_first', itemTypeLabel));
		return false;
	}

	var clientCache = currQryItem.getResult();
	if (!clientCache) {
		return;
	}

	var res;
	var rowIndex = grid.getRowIndex(itemIds[0]);
	var unselIds = [];
	var itemId;
	var itemNode;
	var messageId = (commandId === 'purge') ? 'itemsgrid.purge_confirmation' : 'itemsgrid.delete_confirmation';
	var message;
	var i;
	var j;
	var dialogParams = {
		aras: aras,
		buttons: {
			'btnYes': aras.getResource('', 'itemsgrid.purgedlg_yes'),
			'btnYes4All': aras.getResource('', 'itemsgrid.purgedlg_yes_for_all'),
			'btnSkip': aras.getResource('', 'itemsgrid.purgedlg_skip'),
			'btnCancel': aras.getResource('', 'itemsgrid.purgedlg_cancel')
		},
		defaultButton: 'btnCancel',
		dialogWidth: 400,
		dialogHeight: 200
	};
	var confirmDialogParams = {
		buttons: {
			btnYes: aras.getResource('', 'common.ok'),
			btnCancel: aras.getResource('', 'common.cancel')
		},
		defaultButton: 'btnCancel',
		aras: aras,
		dialogWidth: 300,
		dialogHeight: 200,
		center: true,
		content: 'groupChgsDialog.html'
	};
	var deleteFlag = false;
	var skipDialog = false;
	var executeCommand = function(itemId, itemNode) {
		var res;
		if (commandId == 'purge') {
			res = aras.purgeItem(itemTypeName, itemId, true);
		} else {
			res = aras.deleteItem(itemTypeName, itemId, true);
		}

		if (res) {
			deleteRowSearchGrids(itemNode);

			if (grid.getRowIndex(itemId) > -1) {
				grid.setSelectedRow(itemId, true, false);
				unselIds.push(itemId);
			}
		}
	};
	var indexFor = 0;
	var nextFor = function() {
		indexFor++;
		if (indexFor < itemIds.length) {
			startExecute(itemIds[indexFor], itemIds, indexFor);
		} else {
			if (itemTypeName === 'ItemType') {
				topWnd.updateTree(itemIds);
			}
			topWnd.mainLayout.updateCuiLayoutOnItemChange(itemTypeName);
			if (unselIds.length > 0) {
				for (i = 1; i < unselIds.length; i++) {
					grid.setSelectedRow(unselIds[i], true, false);
				}

				grid.setSelectedRow(unselIds[0], true, true);

				if (itemIds.length > 1) {
					onSelectItem(unselIds[0]);
				}
			} else {
				var rowCount = grid.getRowCount();

				if (rowCount > 0) {
					var idToSelect = grid.getRowId(0);

					if (rowIndex > -1) {
						idToSelect = (rowCount - 1 >= rowIndex) ? grid.getRowId(rowIndex) : grid.getRowId(rowCount - 1);
					}

					grid.setSelectedRow(idToSelect, false, true);
					onSelectItem(idToSelect);
				} else {
					setupGrid(false);
				}
			}
		}
	};

	var startExecute = function(itemId, array, index) {
		var itemNode = clientCache.selectSingleNode('Item[@id="' + itemId + '"]');
		if (!itemNode) {
			deleteRowSearchGrids(itemId);
			nextFor();
			return;
		}

		var tearOffAnsw = execInTearOffWin(itemId, commandId);
		if (tearOffAnsw) {
			if (tearOffAnsw.result === 'Deleted') {
				deleteRow(itemNode);
				focus();
			}
			nextFor();
			return;
		}

		if (!skipDialog) {
			var message = aras.getResource('', messageId, itemTypeLabel, aras.getKeyedNameEx(itemNode));
			if ((array.length - 1) === index) {
				confirmDialogParams.message = message;
				window.parent.ArasModules.Dialog.show('iframe', confirmDialogParams).promise.then(function(res) {
					if (res === 'btnYes') {
						window.setTimeout(function() {
							executeCommand(itemId, itemNode);
							nextFor();
						}, 0);
					} else {
						nextFor();
					}
				});
			} else {
				dialogParams.message = message;
				dialogParams.content = 'groupChgsDialog.html';
				window.parent.ArasModules.Dialog.show('iframe', dialogParams).promise.then(function(res) {
					if (!res || res === 'btnCancel') {
						grid.setSelectedRow(itemId, true, false);
						unselIds.push(itemId);
						skipDialog = true;
					} else if (res === 'btnYes4All') {
						executeCommand(itemId, itemNode);
						skipDialog = true;
						deleteFlag = true;
					} else if (res === 'btnYes') {
						executeCommand(itemId, itemNode);
					}
					window.setTimeout(nextFor, 0);
				});
			}
		} else if (deleteFlag) {
			executeCommand(itemId, itemNode);
			nextFor();
		} else {
			grid.setSelectedRow(itemId, true, false);
			unselIds.push(itemId);
			nextFor();
		}
	};
	startExecute(itemIds[indexFor], itemIds, indexFor);
}

function onSaveAsCommand() {
	var itemId = grid.selection_Experimental.get('id');

	if (!itemId) {
		aras.AlertError(aras.getResource('', 'itemsgrid.select_item_type_first', itemTypeLabel));
		return false;
	}

	if (execInTearOffWin(itemId, 'saveAs')) {
		return true;
	} else {
		var copiedItem = aras.copyItem(itemTypeName, itemId);

		if (copiedItem) {
			var rowId = copiedItem.getAttribute('id');

			if (itemTypeName == 'ItemType') {
				topWnd.updateTree(itemId.split(';'));
			}
			grid.selection_Experimental.clear();

			callbackF_afterAddRow = function() {
				callbackF_afterAddRow = null;
				onSelectItem(rowId);

				if ('File' !== itemTypeName) {
					onEditCommand();
				}
			};

			insertRowSearchGrids(copiedItem);
		} else {
			return false;
		}
	}
}

function onPrintCommand() {
	topWnd.aras.showStatusMessage('status', 'Generation pdf file', '../images/Progress.gif');
	function printGrid(jsPDF) {
		// return array of object about header (header label, widht)
		function getHeaderData() {
			var headerData = [];
			this.grid._grid.settings.indexHead.forEach(function(columnName) {
				var columnIndex = this.grid.getColumnIndex(columnName);

				headerData.push({
					label: grid.getHeaderCol(columnIndex),
					width: grid.getColWidth(columnIndex) + 'px'
				});
			});
			return headerData;
		}

		// return array of object about search bar (search label, widget class name)
		function getSearchBarData() {
			var searchBarData = [];
			this.grid._grid.settings.indexHead.forEach(function(columnName) {
				searchBarData.push({
					label: grid._grid.head.get(columnName, 'searchValue'),
					widget: 'dijit.form.TextBox'
				});
			});
			return searchBarData;
		}

		// fetch items in grid, if items have not been loaded
		function fetchItems() {
			var result = [];
			var onComplete = function(items) {
				result = items;
			};
			grid.grid_Experimental.store.fetch({
				start: 0,
				count: grid.getRowCount(),
				sort: grid.grid_Experimental.getSortProps(),
				onComplete: onComplete
			});
			return result;
		}

		// return array of records Ids stored in grid
		function fetchRecordsIds(items) {
			var result = [];
			var i;
			var length = items.length;
			for (i = 0; i < length; i += 1) {
				result.push(grid.grid_Experimental.store.getIdentity(items[i]));
			}
			return result;
		}

		// forced load items to grid
		function fetchAllItems() {
			grid.grid_Experimental._clearData();
			grid.grid_Experimental.store.fetch({
				start: 0,
				count: grid.getRowCount(),
				sort: grid.grid_Experimental.getSortProps(),
				onComplete: grid.grid_Experimental._onFetchComplete
			});
		}

		// return array of objects about all rows in grid
		function getRowData() {
			var data = [];
			var selectedRowIds = grid.getSelectedItemIds(';').split(';');
			var records = [];
			var itemsExist = true;

			// load records Ids (used if records have not been loaded)
			function loadRecordsIds() {
				itemsExist = false;
				var items = fetchItems();
				records = fetchRecordsIds(items);
				fetchAllItems();
			}

			// if grid does not contain rows, then we are loading them
			if (!grid.getRowId(grid.getRowCount() - 1)) {
				loadRecordsIds();
			}

			for (var j = 0; j < grid.getRowCount(); j++) {
				var rowId = itemsExist ? grid.getRowId(j) : records[j];
				if (!rowId) { // if grid does not contain rows, then we are loading them
					loadRecordsIds();
					rowId = records[j];
				}
				var rowData = [];

				this.grid._grid.settings.indexHead.forEach(function(columnName) { // jshint ignore:line
					var columnIndex = this.grid.getColumnIndex(columnName);
					var cell = grid.cells_Experimental(rowId, columnIndex, true);
					if (cell) {
						rowData.push({
							label: cell.getText(),
							link: this.grid._grid.rows.get(rowId, columnName + 'link'),
							align: cell.getHorAlign(),
							style: cell.getCellStyle(),
							selected: selectedRowIds.indexOf(rowId) > -1 ? true : false
						});
					}
				});
				data.push(rowData);
			}
			return data;
		}

		// method calculate how many records can be print on one page of pdf document
		// depending on format paper and orientation
		function getRecordsPerPage(doc, format, orientation, pdf) {
			var pageFormat = doc.getPageFormat(format);
			var pageHeight = orientation === 'p' ? pageFormat[1] : pageFormat[0];
			var margin = pdf.getMargin();

			var headerHeight = margin + pdf.getHeaderHeight() + (grid._grid.view.defaultSettings.search ? pdf.getSearchBarHeight() : 0);
			var totalRecordsHeight = pageHeight - headerHeight - margin;
			var oneRecordHeight = pdf.getRowHeight();

			var recordsPerPage = Math.floor(totalRecordsHeight / oneRecordHeight);
			return recordsPerPage;
		}

		// start of printing
		topWnd.ModulesManager.using(['aras.innovator.Printing/DataGridToPdf']).then(function(pdf) {
			pdf.init().then(function() {
				// jscs:disable
				var doc = new jsPDF('l', 'pt', 'a4', true);
				// jscs:enable
				var langDir = dojoConfig.arasContext.languageDirection;
				doc.setLangDir(langDir);
				var recordsPerPage = getRecordsPerPage(doc, 'a4', 'l', pdf);
				var pageCount = Math.ceil(grid.getRowCount() / recordsPerPage);
				pageCount = pageCount === 0 ? 1 : pageCount;

				// searhbar can be invisible, so we don't need to print it
				var printSearchBar = grid.isInputRowVisible();

				// print header
				var headerInfo = pdf.printHeader(getHeaderData(), doc, pageCount);
				headerInfo.printSearchBar = printSearchBar;

				// print searhBar
				if (printSearchBar) {
					pdf.printSearchBar(getSearchBarData(), headerInfo, doc, pageCount);
				}

				// print rows
				pdf.printGridData(getRowData(), headerInfo, doc, recordsPerPage);

				// save to file
				doc.save(itemTypeName ? itemTypeName + 'Grid.pdf' : 'print_result.pdf');
				topWnd.aras.clearStatusMessage('status');
			});
		});
	}
	topWnd.ModulesManager.using(['aras.innovator.Printing/JsPdfLoader']).then(function(loader) {
		loader.loadScripts(printGrid, ['jspdf.plugin.text.js', 'jspdf.plugin.bidi.js', 'jspdf.plugin.graphics.js']);
	});
}

function getRealItemTypeNames(itemIdsOrId) {
	var itemIds = itemIdsOrId;
	var resultNames = {};
	var itemNode;
	var items;
	var idList;
	var response;
	var i;

	if (typeof (itemIds) === 'string') {
		itemIds = [itemIds];
	}
	if (!itemIds.length) {
		throw new Error(1, 'Item ids are not specified');
	}

	if (aras.isPolymorphic(currItemType)) {
		idList = itemIds.join(',');

		if (!idList) {
			throw new Error(1, 'IDs list is empty');
		} else {
			response = aras.soapSend('ApplyItem', '<Item type=\'' + itemTypeName + '\' action=\'get\' select=\'itemtype\' idlist=\'' + idList + '\'/>');

			if (response.getFaultCode() != 0) {
				aras.AlertError(response);
				return resultNames;
			}

			items = response.getResult().selectNodes('Item');
			for (i = 0; i < items.length; i++) {
				itemNode = items[i];
				resultNames[itemNode.getAttribute('id')] = aras.getItemTypeName(aras.getItemProperty(itemNode, 'itemtype'));
			}
		}
	} else {
		for (i = 0; i < itemIds.length; i++) {
			resultNames[itemIds[i]] = itemTypeName;
		}
	}

	return resultNames;
}

function onLockCommand(ignorePolymophicWarning, itemIDs) {
	return ItemTypeGrid.onLockCommand(ignorePolymophicWarning, itemIDs);
}

function onUnlockCommand(ignorePolymophicWarning, itemIDs) {
	return ItemTypeGrid.onUnlockCommand(ignorePolymophicWarning, itemIDs);
}

function onRevisionsCommand() {
	var itemId = grid.getSelectedId();

	if (!itemId) {
		aras.AlertError(aras.getResource('', 'itemsgrid.select_item_type_first', itemTypeLabel));
		return false;
	}

	if (execInTearOffWin(itemId, 'revisions')) {
		return true;
	} else {
		var minDialogWidth = 500;
		var maxDialogWidth = document.getElementById('grid_table').offsetWidth - document.getElementById('itemProperties').offsetWidth;
		var width = maxDialogWidth;
		var colWidths = aras.getPreferenceItemProperty('Core_ItemGridLayout', itemTypeID, 'col_widths', null);
		var dialogParams = {
			aras: aras,
			itemID: itemId,
			itemTypeName: itemTypeName,
			dialogWidth: (width < minDialogWidth) ? minDialogWidth : ((width > maxDialogWidth) ? maxDialogWidth : width),
			resizable: true,
			title: aras.getResource('', 'revisiondlg.item_versions'),
			type: 'RevisionsDialog'
		};

		if (colWidths) {
			var widthsArray = colWidths.split(';');
			var i;

			width = 0;
			for (i = 0; i < widthsArray.length; i++) {
				width += parseInt(widthsArray[i]);
			}
		}
		window.parent.ArasModules.Dialog.show('iframe', dialogParams);
	}
}

function onUndoCommand() {
	var itemIDs = topWnd.work.grid.getSelectedItemIds();
	if (itemIDs.length === 0) {
		aras.AlertError(aras.getResource('', 'itemsgrid.select_item_type_first', itemTypeLabel));
		return;
	}

	var dialogParams = {
		aras: aras,
		dialogWidth: 400,
		dialogHeight: 200,
		center: true,
		buttons: {
			btnYes: aras.getResource('', 'itemsgrid.undodlg.yes'),
			btnYes4All: aras.getResource('', 'itemsgrid.undodlg.yes4all'),
			btnSkip: aras.getResource('', 'itemsgrid.undodlg.skip'),
			btnCancel: aras.getResource('', 'itemsgrid.undodlg.cancel')
		},
		defaultButton: 'btnSkip',
	};
	var yes4All = false;
	var index = 0;
	var underCommand = function(itemId) {
		aras.removeFromCache(itemId);
		var itemNode = aras.getItemById(itemTypeName, itemId, 0);

		if (!(itemNode && updateRow(itemNode) === false)) {
			index++;
			nextFor();
		}
	};
	var nextFor = function() {
		if (index < itemIDs.length) {
			var itemId = itemIDs[index];
			var itemNode = aras.getFromCache(itemId);

			if (itemNode) {
				if (execInTearOffWin(itemId, 'undo')) {
					index++;
					nextFor();
				}

				if (!yes4All) {
					var confirmMessage = aras.getResource('', 'itemsgrid.undo_will_discard_changes', itemTypeLabel, aras.getKeyedNameEx(itemNode));
					if (index === itemIDs.length - 1) {
						topWnd.aras.confirm(confirmMessage, window.parent,
							function(res) {
								if (res === 'btnYes') {
									underCommand(itemId);
								} else {
									onSelectItem(itemIDs[0]);
								}
							}
						);
					} else {
						dialogParams.message = confirmMessage;
						dialogParams.content = 'groupChgsDialog.html';
						window.parent.ArasModules.Dialog.show('iframe', dialogParams).promise.then(function(res) {
							if (res === 'btnYes4All') {
								yes4All = true;
								underCommand(itemId);
							} else if (res === 'btnYes') {
								window.setTimeout(function() {
									underCommand(itemId);
								}, 0);
							} else if (res === 'btnSkip') {
								index++;
								window.setTimeout(function() {
									nextFor();
								}, 0);
							} else {
								onSelectItem(itemIDs[0]);
							}
						});
					}
				} else {
					underCommand(itemId);
				}
			}
		} else {
			onSelectItem(itemIDs[0]);
		}
	};
	nextFor();
}

function onOpenCommand() {
	if (itemTypeName == 'File') {
		var itemID = grid.getSelectedId();

		if (!itemID) {
			aras.AlertError(aras.getResource('', 'itemsgrid.select_item_type_first', itemTypeLabel));
			return false;
		}

		if (execInTearOffWin(itemID, 'open')) {
			return true;
		} else {
			var file = aras.getItemById('File', itemID, 0);

			if (file) {
				aras.uiShowItemEx(file, 'openFile');
			}
		}
	} else {
		return false;
	}
}

function onDownloadCommand() {
	if (itemTypeName === 'File') {
		var itemIDs = grid.getSelectedItemIds();

		if (!itemIDs || !itemIDs.length) {
			aras.AlertError(aras.getResource('', 'itemsgrid.select_item_type_first', itemTypeLabel));
			return false;
		}

		for (var i = 0; i < itemIDs.length; i++) {
			var file = aras.getItemById('File', itemIDs[i], 0);
			if (file) {
				aras.downloadFile(file);
			}
		}

		return true;
	}
	return false;
}

function onPromoteCommand() {
	var itemIds = grid.getSelectedItemIds();
	switch (itemIds.length) {
		case 0:
			aras.AlertError(aras.getResource('', 'itemsgrid.select_item_type_first', itemTypeLabel));
			return;
		case 1:
			singlePromote(itemIds[0]);
			return;
		default:
			ItemTypeGrid.onMassPromote(itemIds);
	}

	function singlePromote(itemId) {
		var queryItem = currQryItem.getResult();
		var itemNode;

		itemNode = aras.getFromCache(itemId) || queryItem.selectSingleNode('Item[@id="' + itemId + '"]');
		if (itemNode) {
			if (execInTearOffWin(itemId, 'promote')) {
				return;
			} else {
				window.parent.ArasModules.Dialog.show('iframe', {
					title: aras.getResource('', 'promotedlg.propmote', aras.getKeyedNameEx(itemNode)),
					item: itemNode,
					aras: aras,
					dialogHeight: 300,
					dialogWidth: 400,
					content: 'promoteDialog.html',
					resizable: true
				}).promise.then(function(res) {
					if (typeof (res) == 'string' && res == 'null') {
						return;
					}

					if (!res) {
						return false;
					}
					if (isVersionableIT) {
						var lastItemVersion = aras.getItemLastVersion(itemTypeName, itemId);
						var oldId = itemId;

						if (lastItemVersion) {
							itemId = lastItemVersion.getAttribute('id');

							if (oldId != itemId) {
								deleteRowSearchGrids(itemNode);
								res = lastItemVersion;
							}
						}
					}

					if (updateRowSearchGrids(res) !== false) {
						onSelectItem(itemId);
					}
				});
			}
		}
	}
}

function onCopy2clipboardCommand() {
	var itemIds = topWnd.work.grid.getSelectedItemIds();
	var resultList = [];
	var itemId;
	var copiedItem;
	var i;

	for (i = 0; i < itemIds.length; i++) {
		itemId = itemIds[i];
		copiedItem = aras.copyRelationship(itemTypeName, itemId);

		if (copiedItem) {
			resultList.push(copiedItem);
		} else {
			aras.AlertError(aras.getResource('', 'itemsgrid.failed2get_itemtype_with_id', itemTypeLabel, itemId));
		}
	}

	aras.clipboard.copy(resultList);
	onSelectItem(itemIDs[0]);
}

function onPasteCommand() {
	var itemIds = topWnd.work.grid.getSelectedItemIds();
	var itemArr = aras.clipboard.paste();
	var itemNode;
	var i;
	var j;

	for (i = 0; i < itemIds.length; i++) {
		itemNode = aras.getItemById(itemTypeName, itemIds[i]);

		if (!itemNode) {
			aras.AlertError(aras.getResource('', 'itemsgrid.failed2get_itemtype_with_id', itemTypeLabel, itemIds[i]));
			return;
		}

		for (j = 0; j < itemArr.length; j++) {
			if (!aras.pasteRelationship(itemNode, itemArr[j])) {
				aras.AlertError(aras.getResource('', 'itemsgrid.pasting_failed'));
				return;
			}
		}
		itemNode.setAttribute('isDirty', '1');

		if (updateRow(itemNode) === false) {
			return;
		}
	}

	aras.AlertSuccess(aras.getResource('', 'itemsgrid.pasting_success'));
}

function onPaste_specialCommand() {
	var itemIds = topWnd.work.grid.getSelectedItemIds();
	var itemsList = [];
	var dialogParams;
	var result;
	var itemNode;
	var i;
	var j;

	for (i = 0; i < itemIds.length; i++) {
		itemNode = aras.getItemById(itemTypeName, itemIds[i]);

		if (!itemNode) {
			aras.AlertError(aras.getResource('', 'itemsgrid.failed2get_itemtype_with_id', itemTypeLabel, itemIds[i]));
			continue;
		}

		itemsList.push(itemNode);
	}

	dialogParams = {
		title: aras.getResource('', 'clipboardmanager.clipboard_manager'),
		aras: aras,
		dialogWidth: 700,
		dialogHeight: 450,
		itemsArr: itemsList,
		srcItemTypeId: itemTypeID,
		content: 'ClipboardManager.html'
	};

	window.parent.ArasModules.Dialog.show('iframe', dialogParams).promise.then(function(result) {
		if (result && result.ids) {
			var clipboardItems = aras.clipboard.clItems;
			var clipboardItem;

			for (i = 0; i < result.ids.length; i++) {
				for (j = 0; j < itemsList.length; j++) {
					itemNode = itemsList[j];
					clipboardItem = clipboardItems[result.ids[i]];

					if (!aras.pasteRelationship(itemNode, clipboardItem, result.as_is, result.as_new)) {
						aras.AlertError(aras.getResource('', 'itemsgrid.pasting_failed'));
						return;
					}

					itemNode.setAttribute('isDirty', '1');
					if (updateRow(itemNode) === false) {
						return;
					}
				}
			}
			aras.AlertSuccess(aras.getResource('', 'itemsgrid.pasting_success'));
		}
		onSelectItem(itemIds[0]);
	});
}

function onShow_clipboardCommand() {
	var itemIds = topWnd.work.grid.getSelectedItemIds();

	window.parent.ArasModules.Dialog.show('iframe', {
		title: aras.getResource('', 'clipboardmanager.clipboard_manager'),
		aras: aras,
		content: 'ClipboardManager.html',
		dialogWidth: 700,
		dialogHeight: 450
	}).promise.then(function() {
		onSelectItem(itemIds[0]);
	});
}

function InitPropertiesContainer() {
	var propertiesTr = document.getElementById('itemProperties');

	if (propertiesTr && currItemType) {
		propertiesTr.lastElementChild.innerHTML = aras.uiDrawItemInfoTable4ItemsGrid(currItemType, ItemTypeGrid.propertiesHelper);
	}
}

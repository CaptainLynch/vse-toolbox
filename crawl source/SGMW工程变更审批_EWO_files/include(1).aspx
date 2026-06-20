
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

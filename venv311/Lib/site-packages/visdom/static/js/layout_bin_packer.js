(function (global, factory) {
  typeof exports === 'object' && typeof module !== 'undefined' ? factory(exports) :
  typeof define === 'function' && define.amd ? define(['exports'], factory) :
  factory((global.Bin = {}));
}(this, function (exports) { 'use strict';

  // I don't think this should have args
  function Bin(content, width) {
    this.width = width || 0;
    this.content = content;
  }

  function mustImplement(name) {
    return function() {
      throw new TypeError("MustImplement: " + name );
    };
  }

  // abstract
  Bin.prototype.objectAt = function (collection, index) {
    return collection[index];
  };

  // abstract: return coordinates of element at index.
  //
  // @param index: index of the element in content
  // @param width: viewport width.
  // @returns {x, y} coordinates of element at index.
  //
  // May reset cached viewport width.
  Bin.prototype.position = mustImplement('position');

  // abstract: reset internal state to be anchored at index.
  // @param index: index of the element in content
  Bin.prototype.flush = mustImplement('flush');

  // abstract: return total content height given viewport width.
  // @param width: viewport width
  //
  // May reset cached viewport width.
  Bin.prototype.height = mustImplement('height');

  // abstract: true if layout places more than one object on a line.
  Bin.prototype.isGrid = mustImplement('isGrid');

  function _rangeError(length, index) {
    throw new RangeError("Parameter must be within: [" + 0 + " and " + length + ") but was: " + index);
  }

  // abstract: returns number of elements in content.
  Bin.prototype.length = function () {
    return this.content.length;
  };

  // maximum offset of content wrt to viewport
  // The amount by which content (after being layed out) is taller than
  // the viewport.
  Bin.prototype.maxContentOffset = function Bin_maxContentOffset(width, height) {
    var contentHeight = this.height(width);
    var maxOffset = Math.max(contentHeight - height, 0);
    return maxOffset;
  }

  // abstract: returns index of first visible item.
  // @param topOffset: scroll position
  // @param width: width of viewport
  // @param height: height of viewport
  //
  Bin.prototype.visibleStartingIndex = mustImplement('visibleStartingIndex');

  // abstract: returns number of items visible in viewport.
  // @param topOffset: scroll position
  // @param width: width of viewport
  // @param height: height of viewport
  Bin.prototype.numberVisibleWithin = mustImplement('numberVisibleWithin');

  Bin.prototype.heightAtIndex = function (index) {
    return this.content[index].height;
  };

  Bin.prototype.widthAtIndex = function (index) {
    return this.content[index].width;
  };

  function Entry(height, width, x, y) {
    this.height   = height;
    this.width    = width;
    this.position = {x:x, y:y};
  }

  function ShelfFirst(content, width) {
    this._super$constructor(content, width);
    this._positionEntries = [];
  }

  ShelfFirst.prototype = Object.create(Bin.prototype);
  ShelfFirst.prototype._super$constructor = Bin;
  ShelfFirst.prototype.isGrid = function ShelfFirst_isGrid(width) {
    if (width != null && width !== this.width) {
      this.flush(0);
      this.width = width;
    }
    var length = this.length();
    var entry;

    // TODO: cache/memoize

    for (var i = 0; i < length; i++) {
      entry = this._entryAt(i);
      if (entry.position.x > 0) {
        return true;
      }
    }

    return false;
  };

  ShelfFirst.prototype.height = function (width) {
    if (width != null && width !== this.width) {
      this.flush(0);
      this.width = width;
    }

    var length = this.length();
    if (length === 0) { return 0; }

    // find tallest in last row, add to Y
    var tallest  = 0;
    var currentY = 0;
    var entry;

    for (var i = length - 1; i >= 0; i--) {
      entry = this._entryAt(i);

      if (currentY > entry.position.y) {
        break; // end of last row
      } else if (tallest < entry.height) {
        tallest = entry.height;
      } else {
        // do nothing
      }

      currentY = entry.position.y;
    }

    return currentY + tallest;
  };

  ShelfFirst.prototype.flush = function (position) {
    var positionEntries = this._positionEntries;
    if (positionEntries.length > position) {
      positionEntries.length = position;
    }
  };

  ShelfFirst.prototype.numberVisibleWithin = function (topOffset, width, height, withPadding) {
    if (width !== this.width) {
      this.flush(0);
      this.width = width;
    }

    var startingIndex = this.visibleStartingIndex(topOffset, width, height);

    return this._numberVisibleWithin(startingIndex, height, withPadding);
  };

  ShelfFirst.prototype._entryAt = function _entryAt(index) {
    var length = this.length();
    var width = this.width;

    if (index >= length) {
      _rangeError(length, index);
    }

    var entry;
    var entries = this._positionEntries;
    var entriesLength = entries.length;
    var startingIndex;

    var y, x, i;
    var rowHeight = 0;
    var rowWidth = 0;

    if (index < entriesLength) {
      return this._positionEntries[index];
    } else if (entriesLength === 0) {
      startingIndex = 0;
      y = 0;
    } else {
      startingIndex = entriesLength - 1;
      entry = this._positionEntries[startingIndex];
      rowWidth = entry.position.x + entry.width;
      rowHeight = entry.height;
      y = entry.position.y;
      startingIndex++;
    }

    for (i = startingIndex; i < index + 1; i++) {
      var currentHeight = this.heightAtIndex(i);
      var currentWidth = this.widthAtIndex(i);

      if (entry && (currentWidth + rowWidth) > width) {
        // new row
        y = entry.position.y + entry.height;
        x = 0;
        rowWidth = 0;
        rowHeight = currentHeight;
      } else {
        x = rowWidth;
      }

      if (currentHeight > rowHeight) {
        rowHeight = currentHeight;
      }

      entry = this._positionEntries[i] = new Entry(rowHeight, currentWidth, x, y);

      rowWidth = x + currentWidth;
    }

    return entry;
  };

  ShelfFirst.prototype._numberVisibleWithin = function (startingIndex, height, withPadding) {
    var count = 0;
    var length = this.length();
    var entry, position;
    var currentY = 0;
    var yOffset = 0;

    if (startingIndex > 0 && startingIndex < length) {
      yOffset = this._entryAt(startingIndex).position.y;
    } else {
      yOffset = 0;
    }

    var firstRowHeight;
    for (var i = startingIndex; i < length; i++) {
      entry = this._entryAt(i);
      position = entry.position;

      if (currentY === position.y) {
        // same row
      } else {
        currentY = position.y - yOffset;
        if (withPadding && !firstRowHeight) {
          firstRowHeight = entry.height;
        }
      }

      if (currentY < height) {
        count++;
      } else if (withPadding) {
        withPadding = false;
        height += Math.max(firstRowHeight, entry.height) + 1;
        count++;
      } else {
        break;
      }
    }

    return count;
  };

  ShelfFirst.prototype.position = function position(index, width) {
    var length = this.length();

    if (length === 0 || index > length) {
      _rangeError(length, index);
    }

    if (width !== this.width) {
      this.flush(0);
      this.width =  width;
    }

    return this._entryAt(index).position;
  };

  ShelfFirst.prototype.visibleStartingIndex = function (topOffset, width, visibleHeight) {
    if (topOffset <= 0 ) { return 0; }

    if (width != null && width!== this.width) {
      this.flush(0);
      this.width = width;
    }
    topOffset = Math.min(topOffset, this.maxContentOffset(width, visibleHeight));

    var height = this.height();
    var length = this.length();

    // Start searching using the last item in the list
    // and the bottom of the list for calculating the average height.

    // This algorithm is necessary for efficiently finding
    // the starting index of a list with variable heights
    // in less than O(n) time.

    // Ideally, the performance will be O(log n).
    // The algorithm implemented assumes that the best case
    // is a list of items with all equal heights.
    // Lists with consistent distributions should arrive
    // at results fairly quickly as well.
    var index = length;
    var bottom = height;
    var previousIndex;

    for (;;) {
      // Try to find an item that straddles the top offset
      // or is flush with it
      var averageHeight = bottom / index;

      // Guess the index based off the average height
      index = Math.min(Math.floor(topOffset / averageHeight), length - 1);
      if (previousIndex === index) {
        return index;
      }

      var entry = this._entryAt(index);
      var position = entry.position;

      var top = position.y;
      bottom = top + entry.height;

      previousIndex = index;

      if (bottom > topOffset) {
        // Walk backwards until we find an item that won't be shown
        while (bottom >= topOffset) {
          previousIndex = index;
          index--;

          if (index === -1) {
            break;
          }
          entry = this._entryAt(index);
          position = entry.position;
          bottom = position.y + entry.height;
        }

        return previousIndex;
      } else if (topOffset === bottom) {
        // Walk forwards until we find the next one- it should be close
        while (bottom <= topOffset) {
          index++;
          entry = this._entryAt(index);
          position = entry.position;
          bottom = position.y + entry.height;
        }
        return index;
      }
    }

    return -1;
  };

  function FixedGrid(content, elementWidth, elementHeight) {
    this._elementWidth =  elementWidth;
    this._elementHeight =  elementHeight;

    this._super$constructor(content);
  }

  FixedGrid.prototype = Object.create(Bin.prototype);
  FixedGrid.prototype._super$constructor = Bin;

  FixedGrid.prototype.flush = function (/* index, to */) {

  };

  FixedGrid.prototype.isGrid = function (width) {
    return (Math.floor(width / this.widthAtIndex(0)) || 1) > 1;
  };

  FixedGrid.prototype.visibleStartingIndex = function (topOffset, width, height) {
    topOffset = Math.min(topOffset, this.maxContentOffset(width, height));
    var columns = Math.floor(width / this.widthAtIndex(0)) || 1;

    return Math.floor(topOffset / this.heightAtIndex(0)) * columns;
  };

  FixedGrid.prototype.numberVisibleWithin = function (topOffset, width, height, withPadding) {
    var startingIndex = this.visibleStartingIndex(topOffset, width, height);
    var columns = Math.floor(width / this.widthAtIndex(0)) || 1;
    var length = this.length();

    var rowHeight = this.heightAtIndex(0);
    var rows = Math.ceil(height / rowHeight);

    var maxNeeded = rows * columns;

    if (withPadding) {
      maxNeeded += columns;
    }

    var potentialVisible = length - startingIndex;

    return Math.max(Math.min(maxNeeded, potentialVisible), 0);
  };

  FixedGrid.prototype.widthAtIndex = function (/* index */) {
    return this._elementWidth;
  };

  FixedGrid.prototype.heightAtIndex = function (/* index */) {
    return this._elementHeight;
  };

  FixedGrid.prototype.position = function (index, width) {
    var length = this.length();
    if (length === 0 || index > length) {
      rangeError(length, index);
    }

    var columns = Math.floor(width / this.widthAtIndex(index)) || 1;

    var x = index % columns * this.widthAtIndex(index) | 0;
    var y = Math.floor(index / columns) * this.heightAtIndex(index);

    return {x:x, y:y};
  };

  FixedGrid.prototype.height = function (visibleWidth) {
    if (typeof visibleWidth !== 'number') {
      throw new TypeError('height depends on the first argument of visibleWidth(number)');
    }
    var length = this.length();
    if (length === 0) { return 0; }

    var columnCount = Math.max(Math.floor(visibleWidth/this.widthAtIndex(0), 1));
    columnCount = columnCount > 0 ? columnCount : 1;
    var rows = Math.ceil(length/columnCount);
    var totalHeight = rows * this.heightAtIndex(0);

    return totalHeight;
  };

  exports.Bin = Bin;
  exports.ShelfFirst = ShelfFirst;
  exports.FixedGrid = FixedGrid;

}));
//# sourceMappingURL=layout-bin-packer.js.map
class EventSystem {
    constructor() {
        this.queue = {};
    }

    publish(event, data) {
        let queue = this.queue[event];

        if (typeof queue === 'undefined') {
            return false;
        }

        queue.forEach((cb) => cb(data));

        return true;
    }

    subscribe(event, callback) {
        if (typeof this.queue[event] === 'undefined') {
            this.queue[event] = [];
        }

        this.queue[event].push(callback);
    }

    //  the callback parameter is optional. Without it the whole event will be removed, instead of
    // just one subscibtion. Enough for simple implementations
    unsubscribe(event, callback) {
        let queue = this.queue;

        if (typeof queue[event] !== 'undefined') {
            if (typeof callback === 'undefined') {
                delete queue[event];
            } else {
                this.queue[event] = queue[event].filter(function(sub) {
                    return sub !== callback;
                })
            }
        }
    }
}

module.exports = new EventSystem();
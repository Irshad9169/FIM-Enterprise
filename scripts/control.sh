#!/bin/bash

# Configuration variables
APP_COMMAND="java -jar /path/to/your/application.jar"
APP_COMMAND="uvicorn app.main:app --host 0.0.0.0 --port 8000"
APP_NAME="Fim_App"
PID_FILE="/var/tmp/${APP_NAME}.pid"

# Function to check if the application is already running
is_running() {
    [ -f "${PID_FILE}" ] && ps -p $(cat "${PID_FILE}") > /dev/null 2>&1
}

# Cleanup function to be executed on exit
cleanup() {
    echo "Caught exit signal, cleaning up..."
    rm -f "${PID_FILE}"
}

# Set a trap to call the cleanup function on script exit
#trap cleanup EXIT

# Start function
start() {
    if is_running; then
        echo "${APP_NAME} is already running."
    else
        echo "Starting ${APP_NAME}..."
        # Start the application in the background and save its PID
        nohup ${APP_COMMAND} > /opt/fim/logs/uvicorn.log 2>&1 &
        echo $! > "${PID_FILE}"
        echo "${APP_NAME} started with PID $(cat "${PID_FILE}")."
    fi
}

# Stop function
stop() {
    if is_running; then
        PID=$(cat "${PID_FILE}")
        echo "Stopping ${APP_NAME} with PID ${PID}..."
        kill "${PID}"
        # Wait for the process to die
        while is_running; do
            echo "Waiting for ${APP_NAME} to shut down..."
            sleep 1
        done
        echo "${APP_NAME} stopped."
    else
        echo "${APP_NAME} is not running."
    fi
}

# Main script logic
case "$1" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        stop
        start
        ;;
    status)
        if is_running; then
            echo "${APP_NAME} is running with PID $(cat "${PID_FILE}")."
        else
            echo "${APP_NAME} is not running."
        fi
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac

exit 0


# Set a trap to call the cleanup function on script exit
#trap cleanup EXIT


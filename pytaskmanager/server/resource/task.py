# -*- coding: utf-8 -*-
"""
Resources below '/<api_base>/task'
"""
import logging
import json

from flask import g, request, url_for
from flask_restful import Resource
from . import with_user_or_node, with_user, only_for
from ._schema import TaskSchema, TaskIncludedSchema
from http import HTTPStatus
from flasgger import swag_from
from pathlib import Path

from pytaskmanager.server import db
from pytaskmanager.server import socketio

module_name = __name__.split('.')[-1]
log = logging.getLogger(module_name)


def setup(api, API_BASE):
    path = "/".join([API_BASE, module_name])
    log.info('Setting up "{}" and subdirectories'.format(path))

    api.add_resource(
        Task,
        path,
        endpoint='task_without_id',
        methods=('GET', 'POST')
    )
    api.add_resource(
        Task,
        path + '/<int:id>',
        endpoint='task_with_id',
        methods=('GET', 'DELETE')
    )
    api.add_resource(
        TaskResult,
        path + '/<int:id>/result',
        endpoint='task_result',
        methods=('GET',)
    )


# ------------------------------------------------------------------------------
# Resources / API's
# ------------------------------------------------------------------------------
class Task(Resource):
    """Resource for /api/task"""

    task_schema = TaskSchema()
    task_result_schema = TaskIncludedSchema()

    @only_for(["user", "node"])
    @swag_from(str(Path(r"swagger/get_task_with_id.yaml")), endpoint='task_with_id')
    @swag_from(str(Path(r"swagger/get_task_without_id.yaml")), endpoint='task_without_id')
    def get(self, id=None):
        task = db.Task.get(id)
        if not task:
            return {"msg": "task id={} is not found"}, HTTPStatus.NOT_FOUND

        s = self.task_result_schema if request.args.get('include') == 'results' else self.task_schema
        return s.dump(task, many=not id).data, HTTPStatus.OK

    @only_for(["user", "container"])
    @swag_from(str(Path(r"swagger/post_task_without_id.yaml")), endpoint='task_without_id')
    def post(self):
        """Create a new Task."""
        data = request.get_json()
        collaboration_id = data.get('collaboration_id')

        if not collaboration_id:
            log.error("JSON causing the error:\n{}".format(data))
            return {"msg": "JSON should contain 'collaboration_id'"}, HTTPStatus.BAD_REQUEST

        collaboration = db.Collaboration.get(collaboration_id)
        if not collaboration:
            return {"msg": "collaboration id={} not found".format(collaboration_id)}, HTTPStatus.NOT_FOUND

        task = db.Task(collaboration=collaboration)
        task.name = data.get('name', '')
        task.description = data.get('description', '')
        task.image = data.get('image', '')

        input_ = data.get('input', '')
        if not isinstance(input_, str):
            input_ = json.dumps(input_)

        task.input = input_
        task.status = "open"
        task.save()

        log.info(f"New task created for collaboration '{task.collaboration.name}'")
        log.debug(f" created by: '{g.user.username}'")
        log.debug(f" url: '{url_for('task_with_id', id=task.id)}'")
        log.debug(f" name: '{task.name}'")
        log.debug(f" image: '{task.image}'")
        log.debug(f"Assigning task to {len(collaboration.nodes)} nodes")


        # a collaboration can include multiple nodes
        for c in collaboration.nodes:
            log.debug(f"   Assigning task to '{c.name}'")
            db.TaskResult(task=task, node=c)

        task.save()

        # if the node is connected send a socket message that there
        # is a new task available
        socketio.emit(
            'new_task', 
            task.id, 
            room='collaboration_'+str(task.collaboration_id),
            namespace='/tasks'
        )

        return self.task_schema.dump(task, many=False)

    @only_for(['user'])
    @swag_from(str(Path(r"swagger/delete_task_with_id.yaml")), endpoint='task_with_id')
    def delete(self, id):
        """Deletes a task"""
        # TODO we might want to delete the corresponding results also?

        task = db.Task.get(id)
        if not task:
            return {"msg": "task id={} not found".format(id)}, HTTPStatus.NOT_FOUND

        task.delete()
        return {"msg": "task id={} successfully deleted".format(id)}, HTTPStatus.OK


class TaskResult(Resource):
    """Resource for /api/task/<int:id>/result"""

    @only_for(['user', 'container'])
    @swag_from(str(Path(r"swagger/get_task_result.yaml")), endpoint='task_result')
    def get(self, id):
        """Return results for task."""
        task = db.Task.get(id)
        if not task:
            return {"msg": "task id={} not found".format(id)}, HTTPStatus.NOT_FOUND

        return task.results, HTTPStatus.OK


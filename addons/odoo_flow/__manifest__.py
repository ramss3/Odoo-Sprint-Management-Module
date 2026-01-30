{
    "name": "Project Sprints",
    "version": "1.0.0",
    "category": "Project",
    "summary": "Add sprint management to projects and tasks",
    "depends": ["project"],
    "data": [
        "security/ir.model.access.csv",
        "views/sprint_views.xml",
        "views/project_task_views.xml",
    ],
    "installable": True,
    "application": False,
}
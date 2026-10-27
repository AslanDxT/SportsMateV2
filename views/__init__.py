"""Page routes, grouped by area."""


def register_blueprints(app):
    from views.activities import bp as activities_bp
    from views.auth import bp as auth_bp
    from views.main import bp as main_bp
    from views.messages import bp as messages_bp
    from views.people import bp as people_bp

    for blueprint in (main_bp, auth_bp, activities_bp, people_bp, messages_bp):
        app.register_blueprint(blueprint)

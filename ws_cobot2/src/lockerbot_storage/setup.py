from setuptools import setup

setup(
    name="lockerbot_storage",
    version="0.1.0",
    packages=["lockerbot_storage"],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/lockerbot_storage"]),
        ("share/lockerbot_storage", ["package.xml"]),
    ],
    install_requires=["setuptools"],
    python_requires=">=3.10",
    description="ROS-independent SQLite attendance and item records",
    license="UNLICENSED",
    maintainer="lockerbot team",
    maintainer_email="seng3340@users.noreply.github.com",
)

FROM gradle:8.5-jdk17 AS build
COPY --chown=gradle:gradle . /home/gradle/src
WORKDIR /home/gradle/src
RUN gradle build --no-daemon && \
    tar -xf build/distributions/kafka-17507-repro.tar -C build/distributions/

FROM --platform=linux/amd64 centos:7

# Fix CentOS 7 EOL repos (mirrorlist.centos.org is dead)
RUN sed -i 's/mirrorlist/#mirrorlist/g' /etc/yum.repos.d/CentOS-*.repo && \
    sed -i 's|#baseurl=http://mirror.centos.org|baseurl=http://vault.centos.org|g' /etc/yum.repos.d/CentOS-*.repo

# Install JRE 17 (Adoptium Temurin)
RUN yum install -y which && \
    cat > /etc/yum.repos.d/adoptium.repo <<'EOF'
[Adoptium]
name=Adoptium
baseurl=https://packages.adoptium.net/artifactory/rpm/centos/7/x86_64
enabled=1
gpgcheck=1
gpgkey=https://packages.adoptium.net/artifactory/api/gpg/key/public
EOF
RUN yum install -y temurin-17-jre && yum clean all

ENV JAVA_HOME=/usr/lib/jvm/temurin-17-jre
ENV PATH="${JAVA_HOME}/bin:${PATH}"

COPY --from=build /home/gradle/src/build/libs/kafka-17507-repro.jar /app/app.jar
COPY --from=build /home/gradle/src/build/distributions/kafka-17507-repro /app/kafka-17507-repro
WORKDIR /app
ENV CLASSPATH="/app/kafka-17507-repro/lib/*:/app/app.jar"

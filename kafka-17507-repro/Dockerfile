FROM gradle:8.5-jdk17 AS build
COPY --chown=gradle:gradle . /home/gradle/src
WORKDIR /home/gradle/src
RUN gradle build --no-daemon && \
    tar -xf build/distributions/kafka-17507-repro.tar -C build/distributions/

FROM eclipse-temurin:17-jre
COPY --from=build /home/gradle/src/build/libs/kafka-17507-repro.jar /app/app.jar
COPY --from=build /home/gradle/src/build/distributions/kafka-17507-repro /app/kafka-17507-repro
WORKDIR /app
ENV CLASSPATH="/app/kafka-17507-repro/lib/*:/app/app.jar"

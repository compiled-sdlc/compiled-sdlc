package org.springframework.samples.petclinic.visits.web;

import java.util.List;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.http.MediaType;
import org.springframework.samples.petclinic.visits.model.Visit;
import org.springframework.samples.petclinic.visits.model.VisitRepository;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.BDDMockito.given;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Acceptance check for CR-104: the visit description never reaches the log.
 */
@WebMvcTest(VisitResource.class)
@ActiveProfiles("test")
class VisitLoggingAcceptanceTest {

    private static final String DESCRIPTION = "confidential clinical detail 8f3ac1";

    @Autowired
    MockMvc mvc;

    @MockitoBean
    VisitRepository visitRepository;

    private ListAppender<ILoggingEvent> appender;

    private Logger rootLogger() {
        return (Logger) LoggerFactory.getLogger(org.slf4j.Logger.ROOT_LOGGER_NAME);
    }

    @BeforeEach
    void captureTheLog() {
        appender = new ListAppender<>();
        appender.start();
        Logger root = rootLogger();
        root.setLevel(Level.INFO);
        root.addAppender(appender);
    }

    @AfterEach
    void releaseTheLog() {
        rootLogger().detachAppender(appender);
        appender.stop();
    }

    @Test
    void shouldNotWriteTheDescriptionToTheLog() throws Exception {
        given(visitRepository.save(any(Visit.class)))
            .willAnswer(invocation -> invocation.getArgument(0));

        mvc.perform(post("/owners/1/pets/7/visits")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"date\":\"2026-08-28\",\"description\":\"" + DESCRIPTION + "\"}"))
            .andExpect(status().isCreated())
            .andExpect(jsonPath("$.description").value(DESCRIPTION));

        List<ILoggingEvent> events = List.copyOf(appender.list);
        assertThat(events)
            .as("the creation is still recorded in the log")
            .anyMatch(event -> event.getLevel() == Level.INFO);
        for (ILoggingEvent event : events) {
            assertThat(event.getFormattedMessage())
                .as("no log line may carry the visit description")
                .doesNotContain(DESCRIPTION);
        }
    }
}
